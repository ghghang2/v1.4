"""Compaction Engine — keeps context within token limits by summarising history."""
from __future__ import annotations

import logging
import threading
from typing import List, Tuple, Optional

from nbchat.ui.chat_builder import build_messages
from .client import get_client

_log = logging.getLogger("nbchat.compaction")
if not _log.handlers:
    _h = logging.FileHandler("compaction.log", mode="a")
    _h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.DEBUG)

_Row = Tuple[str, str, str, str, str]
_DEPENDENT_ROLES = {"tool", "analysis", "assistant_full"}

# Roles that can open a new exchange even within a single user turn.
# Each assistant_full + its tool results form a discrete agentic step.
_EXCHANGE_OPENERS = {"assistant", "assistant_full"}


class CompactionEngine:

    def __init__(self, threshold, tail_messages=5, summary_prompt="",
                 summary_model="", system_prompt=""):
        self.threshold = threshold
        self.tail_messages = tail_messages
        self.summary_prompt = summary_prompt
        self.summary_model = summary_model
        self.system_prompt = system_prompt
        self.context_summary: str = ""
        self._cache: dict = {}
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Token estimation
    # ------------------------------------------------------------------

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 3)

    def total_tokens(self, history: List[_Row]) -> int:
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
        history_tokens = self.total_tokens(history)
        summary_tokens = (
            self._estimate_tokens(self.context_summary)
            if self.context_summary else 0
        )
        tokens = history_tokens + summary_tokens
        trigger = int(self.threshold * 0.75)
        _log.debug(
            f"token estimate: {tokens} "
            f"(history={history_tokens}, summary={summary_tokens}) "
            f"/ {self.threshold} (trigger={trigger})"
        )
        return tokens >= trigger

    # ------------------------------------------------------------------
    # Grouping into compactable units
    # ------------------------------------------------------------------

    @staticmethod
    def _group_into_units(history: List[_Row]) -> List[List[_Row]]:
        """Split history into the finest compactable units possible.

        Primary split: at each ``user`` row (conversation turns).
        Secondary split: within a turn, at each ``assistant`` or
        ``assistant_full`` row — each agentic step (assistant + its tool
        results) forms its own unit.  This handles the common case of a
        long single-turn agentic loop where the user sends one message and
        the assistant makes 30+ tool calls.

        A unit is always structurally self-contained: it never begins with
        a dependent role (tool / analysis) that requires a preceding row.
        """
        units: List[List[_Row]] = []
        current: List[_Row] = []

        for row in history:
            role = row[0]

            if role == "user":
                # User row always starts a new unit.
                if current:
                    units.append(current)
                current = [row]

            elif role in _EXCHANGE_OPENERS and current:
                # Start a new agentic-step unit, but only if the current unit
                # already has content (avoid empty leading units).
                # Exception: if the current unit's last row is also an opener
                # with no tool results yet, keep accumulating.
                last_role = current[-1][0]
                if last_role not in _EXCHANGE_OPENERS:
                    units.append(current)
                    current = [row]
                else:
                    current.append(row)

            else:
                current.append(row)

        if current:
            units.append(current)

        _log.debug(f"_group_into_units: {len(history)} rows -> {len(units)} units")
        return units

    # ------------------------------------------------------------------
    # Safe tail — never returns empty
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_tail(history: List[_Row], n: int) -> List[_Row]:
        if not history or n <= 0:
            return history

        tail_start = max(0, len(history) - n)

        probe = tail_start
        while probe < len(history) and history[probe][0] in _DEPENDENT_ROLES:
            probe += 1
        if probe < len(history):
            return history[probe:]

        probe = len(history) - 1
        while probe > 0 and history[probe][0] != "user":
            probe -= 1
        if history[probe][0] == "user":
            _log.debug(f"_safe_tail: fell back to user boundary at index {probe}")
            return history[probe:]

        _log.debug("_safe_tail: no user boundary found, returning full history")
        return history

    # ------------------------------------------------------------------
    # Tool result truncation
    # ------------------------------------------------------------------

    @staticmethod
    def _truncate_tool_results(rows: List[_Row], budget: int) -> List[_Row]:
        def est(text: str) -> int:
            return max(1, len(text) // 3)

        result = list(rows)
        total = sum(est(r[1]) + (est(r[4]) if r[4] else 0) for r in result)

        if total <= budget:
            return result

        tool_indices = sorted(
            [i for i, r in enumerate(result) if r[0] == "tool"],
            key=lambda i: len(result[i][1]),
            reverse=True,
        )

        for idx in tool_indices:
            if total <= budget:
                break
            role, content, tid, tname, targs = result[idx]
            excess_chars = (total - budget) * 3
            keep = max(200, len(content) - excess_chars)
            notice = (
                f"\n[...output truncated from {len(content)} to {keep} chars"
                f" to fit context window...]"
            )
            new_content = content[:keep] + notice
            saved = est(content) - est(new_content)
            result[idx] = (role, new_content, tid, tname, targs)
            total -= saved
            _log.debug(
                f"truncated tool result '{tname}' "
                f"{len(content)} -> {len(new_content)} chars"
            )

        return result

    # ------------------------------------------------------------------
    # Core compaction
    # ------------------------------------------------------------------

    def compact_history(self, history: List[_Row]) -> List[_Row]:
        _log.debug(
            f"compact_history called, history len={len(history)}, "
            f"tail_messages={self.tail_messages}"
        )

        if len(history) <= self.tail_messages:
            _log.debug("history too short to compact")
            return history

        units = self._group_into_units(history)

        if len(units) <= 1:
            # Only one unit and it's already over budget — truncate its tool
            # results so it fits, there's nothing older to summarise.
            _log.debug(
                "only one unit — truncating tool results to fit budget"
            )
            tail_budget = int(self.threshold * 0.50)
            truncated = self._truncate_tool_results(history, tail_budget)
            # Still produce a summary stub so context_summary is non-empty
            # and the model knows something was trimmed.
            self.context_summary = (
                (self.context_summary + "\n" if self.context_summary else "") +
                "[Earlier tool outputs were truncated to fit the context window.]"
            )
            with self._cache_lock:
                self._cache.clear()
            return truncated

        # Keep the last N units as the tail (N chosen so row count >= tail_messages).
        tail_units: List[List[_Row]] = []
        tail_row_count = 0
        for unit in reversed(units):
            tail_units.insert(0, unit)
            tail_row_count += len(unit)
            if tail_row_count >= self.tail_messages:
                break

        older_units = units[:len(units) - len(tail_units)]

        if not older_units:
            _log.debug("no older units to summarise — keeping full history")
            return history

        to_summarise = [row for u in older_units for row in u]
        remaining_history = [row for u in tail_units for row in u]

        # Truncate oversized tool results in the tail so retained rows
        # don't themselves blow the budget.
        tail_budget = int(self.threshold * 0.50)
        remaining_history = self._truncate_tool_results(remaining_history, tail_budget)

        _log.debug(
            f"summarising {len(to_summarise)} rows "
            f"({len(older_units)} units), "
            f"keeping {len(remaining_history)} rows "
            f"({len(tail_units)} units)"
        )

        self.context_summary = self._call_summariser(to_summarise)

        with self._cache_lock:
            self._cache.clear()

        return remaining_history

    # ------------------------------------------------------------------
    # Summariser call
    # ------------------------------------------------------------------

    def _call_summariser(self, older: List[_Row]) -> str:
        older = self._truncate_tool_results(older, self.threshold * 2)
        messages = build_messages(older, self.system_prompt)

        if self.context_summary:
            messages.insert(1, {
                "role": "system",
                "content": (
                    "Previous conversation summary (incorporate this into your"
                    f" new summary):\n{self.context_summary}"
                ),
            })

        for msg in messages:
            msg.pop("reasoning_content", None)

        if messages and messages[-1].get("role") == "assistant":
            messages[-1].pop("tool_calls", None)
            if not messages[-1].get("content"):
                messages.pop()

        messages.append({
            "role": "user",
            "content": this.summary_prompt,
        })

        _log.debug(f"sending {len(messages)} messages to summariser")

        try:
            response = get_client().chat.completions.create(
                model=self.summary_model,
                messages=messages,
                max_tokens=4096,
            )
        except Exception as exc:
            raise RuntimeError(f"Summarisation failed: {exc}") from exc

        summary = response.choices[0].message.content
        _log.debug(
            f"summary produced ({len(summary)} chars): {summary[:120]}..."
        )
        return summary


__all__ = ["CompactionEngine"]