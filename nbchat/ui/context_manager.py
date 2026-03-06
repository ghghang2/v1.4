"""Context management mixin for ChatUI.

Handles the sliding window, hard trim, and task log — the three mechanisms
that keep the messages list within the model's context limit.
"""
from __future__ import annotations

from nbchat.core.utils import lazy_import

import json
import logging
from typing import List, Tuple

_log = logging.getLogger("nbchat.compaction")

_Row = Tuple[str, str, str, str, str]


class ContextMixin:
    """Mixed into ChatUI — expects self.history, self.task_log,
    self.system_prompt, self.session_id, and lazy_import to exist."""

    # ------------------------------------------------------------------
    # Sliding window
    # ------------------------------------------------------------------

    def _window(self) -> List[_Row]:
        """Return the last WINDOW_TURNS user turns of history.

        self.history is never modified — only what the model sees is trimmed.
        Always starts on a user row so message ordering is never broken.
        """
        user_count = 0
        for i in range(len(self.history) - 1, -1, -1):
            if self.history[i][0] == "user":
                user_count += 1
                if user_count == self.WINDOW_TURNS:
                    return list(self.history[i:])
        return list(self.history)

    # ------------------------------------------------------------------
    # Hard trim — called immediately before every API call
    # ------------------------------------------------------------------

    def _hard_trim(self, messages: list) -> None:
        """Enforce a hard token budget by dropping oldest complete exchanges.

        An exchange is one assistant-with-tool-calls message plus all the
        tool-result messages that immediately follow it.  Exchanges are
        always dropped as a complete atomic unit so the message sequence
        is never broken (the server errors if a tool message lacks a
        preceding assistant tool_call).

        Strategy:
        1. Identify all droppable exchange blocks in messages.
        2. Keep at least KEEP_RECENT_EXCHANGES most recent exchanges intact.
        3. Drop oldest exchange blocks until under budget.
        4. Last resort: truncate the content of the largest tool result.
        """
        config = lazy_import("nbchat.core.config")  # noqa: F821 — provided by ChatUI
        limit = int(config.CONTEXT_TOKEN_THRESHOLD * 0.85)

        def est(msg: dict) -> int:
            content = msg.get("content") or ""
            tcs = msg.get("tool_calls") or []
            tc_text = "".join(
                tc.get("function", {}).get("arguments", "") for tc in tcs
            )
            return max(1, (len(content) + len(tc_text)) // 3)

        def total() -> int:
            return sum(est(m) for m in messages)

        if total() <= limit:
            return

        # Build an ordered list of (start, end) index pairs for every
        # assistant+tool_calls exchange in messages (excluding index 0).
        exchanges = []
        i = 1
        while i < len(messages):
            m = messages[i]
            if m.get("role") == "assistant" and m.get("tool_calls"):
                start = i
                end = i + 1
                while end < len(messages) and messages[end].get("role") == "tool":
                    end += 1
                exchanges.append((start, end))
                i = end
            else:
                i += 1

        # Drop oldest exchanges, always keeping KEEP_RECENT_EXCHANGES.
        KEEP_RECENT_EXCHANGES = 6
        droppable = exchanges[:-KEEP_RECENT_EXCHANGES] if len(exchanges) > KEEP_RECENT_EXCHANGES else []

        offset = 0  # track index shift as we delete
        for start, end in droppable:
            if total() <= limit:
                break
            s = start - offset
            e = end - offset
            _log.debug(
                f"_hard_trim: dropping exchange [{s}:{e}] "
                f"({e-s} messages), total now {total()}"
            )
            # Before dropping, append a one-liner to the system message
            # so the model retains awareness of what was found.
            dropped_summaries = [
                messages[s + i].get("content", "")[:120]
                for i in range(1, e - s)
                if messages[s + i].get("role") == "tool"
            ]
            if dropped_summaries and messages and messages[0].get("role") == "system":
                note = " | ".join(dropped_summaries)
                messages[0]["content"] += f"\n[earlier result: {note}]"

            del messages[s:e]
            offset += (end - start)

        # Last resort: truncate the largest tool result.
        while total() > limit:
            tool_indices = [
                i for i, m in enumerate(messages)
                if m.get("role") == "tool"
            ]
            if not tool_indices:
                break
            largest = max(tool_indices, key=lambda i: len(messages[i].get("content", "")))
            original = messages[largest].get("content", "")
            if len(original) <= 200:
                break  # already tiny, nothing left to trim
            messages[largest]["content"] = (
                original[:200]
                + f"\n[...truncated {len(original)-200} chars to fit context...]"
            )
            _log.debug(
                f"_hard_trim: truncated tool result at [{largest}] "
                f"{len(original)} -> 200 chars"
            )

    # ------------------------------------------------------------------
    # Task log
    # ------------------------------------------------------------------

    def _log_action(self, tool_name: str, tool_args: str, result: str) -> None:
        """Append one line to the task log for this tool call."""
        db = lazy_import("nbchat.core.db")  # noqa: F821
        try:
            args_obj = json.loads(tool_args)
            hint = next(
                (str(v)[:60] for v in args_obj.values() if isinstance(v, str)),
                tool_args[:60],
            )
        except Exception:
            hint = tool_args[:60]

        first_line = result.split("\n")[0][:120]
        if first_line.strip() == "NO_RELEVANT_OUTPUT":
            first_line = "(no relevant output)"

        entry = f"{tool_name}({hint}) → {first_line}"
        self.task_log.append(entry)
        if len(self.task_log) > 30:
            self.task_log = self.task_log[-30:]
        db.save_task_log(self.session_id, self.task_log)
        _log.debug(f"task_log: {entry}")