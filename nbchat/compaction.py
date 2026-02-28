"""Compaction Engine
===================

Keeps the token count sent to the model under a configured threshold by
summarising the oldest portion of the conversation.

Key design decisions
--------------------
* History is never mutated with a ``compacted`` row.  Instead, the summary
  lives in ``context_summary`` on the engine and is injected into the system
  prompt by ``chat_builder.build_messages``.  This keeps the stored history
  append-only and makes the split logic much simpler.

* Splitting is turn-aware.  History is first grouped into logical *turns*
  (each starting with a ``user`` row).  Compaction drops whole turns from the
  front, so we never accidentally split an ``assistant_full`` / ``tool`` /
  ``analysis`` triplet.

* For pathological cases where a single turn exceeds the threshold on its own
  (very long agentic loops), ``_find_safe_split`` scans forward within the
  turn for the first row whose role cannot be a structural *dependent* of the
  row before it.  This is a last resort — whole-turn dropping is always
  preferred.

* Successive compactions are cumulative: the previous ``context_summary`` is
  fed to the summariser so the new summary folds it in without an extra API
  call.
"""
from __future__ import annotations

import sys
import threading
from typing import List, Tuple, Optional

from nbchat.ui.chat_builder import build_messages
from nbchat.core.client import get_client

# Type alias for readability
_Row = Tuple[str, str, str, str, str]

# Roles that must never begin a tail slice because they depend on a preceding
# assistant_full (or analysis) row to be structurally valid.
_DEPENDENT_ROLES = {"tool", "analysis", "assistant_full"}


class CompactionEngine:
    """Lightweight engine for keeping chat history within token limits.

    Parameters
    ----------
    threshold:
        Maximum token budget.  Compaction is triggered at 75 % of this value.
    tail_messages:
        Minimum number of history *rows* to keep verbatim (used as a floor
        when no turn boundary can be found).
    summary_prompt:
        The text the engine sends to the model as the *assistant* turn that
        starts the summary.  The model is expected to continue/complete it.
    summary_model:
        Model identifier used for summarisation.
    system_prompt:
        System prompt forwarded to the summariser for full context.
    """

    def __init__(
        self,
        threshold: int,
        tail_messages: int = 5,
        summary_prompt: str = "",
        summary_model: str = "",
        system_prompt: str = "",
    ) -> None:
        self.threshold = threshold
        self.tail_messages = tail_messages
        self.summary_prompt = summary_prompt
        self.summary_model = summary_model
        self.system_prompt = system_prompt

        # The rolling summary produced by previous compactions.
        # Injected into the system prompt via build_messages; never stored as
        # a history row.
        self.context_summary: str = ""

        self._cache: dict = {}
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Token estimation
    # ------------------------------------------------------------------

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 3)

    def total_tokens(self, history: List[_Row]) -> int:
        """Approximate token count across all history rows."""
        total = 0
        for role, content, tool_id, tool_name, tool_args in history:
            key = hash((content, tool_args))
            with self._cache_lock:
                cached = self._cache.get(key)
            if cached is not None:
                total += cached
                continue
            tokens = self._estimate_tokens(content) + (
                self._estimate_tokens(tool_args) if tool_args else 0
            )
            with self._cache_lock:
                self._cache[key] = tokens
            total += tokens
        return total

    def should_compact(self, history: List[_Row]) -> bool:
        """Return True when the history is approaching the token threshold."""
        tokens = self.total_tokens(history)
        trigger = int(self.threshold * 0.75)
        print(
            f"[compaction] token estimate: {tokens} / {self.threshold}"
            f" (trigger={trigger})",
            file=sys.stderr,
        )
        return tokens >= trigger

    # ------------------------------------------------------------------
    # Turn grouping
    # ------------------------------------------------------------------

    @staticmethod
    def _group_into_turns(history: List[_Row]) -> List[List[_Row]]:
        """Split history into logical turns, each beginning with a user row.

        Any rows that appear before the first ``user`` row (e.g. a legacy
        ``compacted`` row) are bundled into their own leading group so they
        are never silently dropped.
        """
        turns: List[List[_Row]] = []
        current: List[_Row] = []
        for row in history:
            if row[0] == "user" and current:
                turns.append(current)
                current = []
            current.append(row)
        if current:
            turns.append(current)
        return turns

    # ------------------------------------------------------------------
    # Intra-group safe split (last resort for oversized agentic turns)
    # ------------------------------------------------------------------

    @staticmethod
    def _find_safe_split(group: List[_Row]) -> Optional[int]:
        """Return the earliest index *i* inside *group* such that
        ``group[i:]`` is structurally self-contained.

        A position is safe when ``group[i]`` is not a dependent role AND
        ``group[i-1]`` is not ``assistant_full`` (which must be followed by
        its tool results before the chain is complete).

        Returns ``None`` if no safe split exists (caller should keep the
        whole group).
        """
        for i in range(1, len(group)):
            role = group[i][0]
            prev_role = group[i - 1][0]
            if role not in _DEPENDENT_ROLES and prev_role != "assistant_full":
                return i
        return None

    # ------------------------------------------------------------------
    # Core compaction
    # ------------------------------------------------------------------

    def compact_history(self, history: List[_Row]) -> List[_Row]:
        """Summarise the oldest portion of *history* and return the remainder.

        The summary is stored in ``self.context_summary`` and folded into the
        next call to ``build_messages`` via the ``context_summary`` parameter.
        No ``compacted`` row is inserted into the returned history.

        If a previous summary exists it is provided to the summariser so the
        new summary is cumulative (the model merges old + new context).
        """
        print(
            f"[compaction] compact_history called,"
            f" history len={len(history)},"
            f" tail_messages={self.tail_messages}",
            file=sys.stderr,
        )

        if len(history) <= self.tail_messages:
            print("[compaction] history too short to compact", file=sys.stderr)
            return history

        turns = self._group_into_turns(history)
        threshold_tokens = int(self.threshold * 0.75)

        # Walk turns from oldest, accumulating rows to summarise, until what
        # remains fits comfortably within the token budget.
        to_summarise: List[_Row] = []
        remaining_turns: List[List[_Row]] = list(turns)

        while remaining_turns:
            # Flatten remaining turns to check token count.
            remaining_flat = [row for t in remaining_turns for row in t]
            if self.total_tokens(remaining_flat) <= threshold_tokens:
                break  # Remaining history already fits.

            candidate_turn = remaining_turns[0]

            # If dropping this turn would leave nothing, try an intra-turn
            # split instead of dropping everything.
            after_drop = [row for t in remaining_turns[1:] for row in t]
            if not after_drop:
                split_idx = self._find_safe_split(candidate_turn)
                if split_idx is not None:
                    to_summarise.extend(candidate_turn[:split_idx])
                    remaining_turns[0] = candidate_turn[split_idx:]
                    print(
                        f"[compaction] intra-turn split at index {split_idx}"
                        f" within last turn of {len(candidate_turn)} rows",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "[compaction] cannot split last remaining turn,"
                        " aborting compaction",
                        file=sys.stderr,
                    )
                break

            # If the candidate turn alone exceeds the threshold, split it
            # rather than dropping it wholesale so the summariser sees all
            # the content it should.
            turn_tokens = self.total_tokens(candidate_turn)
            if turn_tokens >= threshold_tokens:
                split_idx = self._find_safe_split(candidate_turn)
                if split_idx is not None:
                    to_summarise.extend(candidate_turn[:split_idx])
                    remaining_turns[0] = candidate_turn[split_idx:]
                    print(
                        f"[compaction] oversized turn ({turn_tokens} tokens):"
                        f" intra-turn split at index {split_idx}",
                        file=sys.stderr,
                    )
                    continue
                # No safe split — drop the whole oversized turn rather than
                # overflow the context window.
                print(
                    f"[compaction] oversized turn with no safe split"
                    f" ({turn_tokens} tokens) — dropping whole turn",
                    file=sys.stderr,
                )

            to_summarise.extend(remaining_turns.pop(0))

        if not to_summarise:
            print("[compaction] nothing to summarise", file=sys.stderr)
            return history

        remaining_history = [row for t in remaining_turns for row in t]
        print(
            f"[compaction] summarising {len(to_summarise)} rows,"
            f" keeping {len(remaining_history)} rows",
            file=sys.stderr,
        )

        self.context_summary = self._call_summariser(to_summarise)

        with self._cache_lock:
            self._cache.clear()

        return remaining_history

    # ------------------------------------------------------------------
    # Summariser call
    # ------------------------------------------------------------------

    def _call_summariser(self, older: List[_Row]) -> str:
        """Send *older* rows to the summarisation model and return the text.

        If ``self.context_summary`` is non-empty it is injected as an extra
        system message before the older history so the model can fold the
        previous summary into the new one — no extra API round-trip needed.
        """
        messages = build_messages(older, self.system_prompt)

        # Inject the previous rolling summary so the model merges it.
        if self.context_summary:
            # Insert right after the system prompt (index 0).
            messages.insert(1, {
                "role": "system",
                "content": (
                    "Previous conversation summary (incorporate this into your"
                    f" new summary):\n{self.context_summary}"
                ),
            })

        # Strip output-only fields that inference servers reject.
        for msg in messages:
            msg.pop("reasoning_content", None)

        # Remove dangling tool_calls from the last assistant message so the
        # summariser does not see an incomplete tool-call sequence.
        if messages and messages[-1].get("role") == "assistant":
            messages[-1].pop("tool_calls", None)
            if not messages[-1].get("content"):
                messages.pop()

        # Two-turn prompt that elicits the summary.
        messages.append({"role": "user", "content": "we are running out of context window"})
        messages.append({"role": "assistant", "content": self.summary_prompt})

        print(
            f"[compaction] sending {len(messages)} messages to summariser",
            file=sys.stderr,
        )

        try:
            response = get_client().chat.completions.create(
                model=self.summary_model,
                messages=messages,
                max_tokens=4096,
            )
        except Exception as exc:
            raise RuntimeError(f"Summarisation failed: {exc}") from exc

        summary = response.choices[0].message.content
        print(
            f"[compaction] summary produced ({len(summary)} chars):"
            f" {summary[:120]}...",
            file=sys.stderr,
        )
        return summary


__all__ = ["CompactionEngine"]