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
        """Return a bounded slice of history for the model context.

        Limits by WINDOW_TURNS user turns AND by MAX_WINDOW_ROWS to
        prevent massive rebuilds when a single turn had many exchanges.
        Always starts on a user row.
        Falls back to full history if fewer than WINDOW_TURNS user messages exist.
        """
        MAX_WINDOW_ROWS = 30  # hard row cap regardless of turn count

        # Walk backward counting user rows to find the cut point.
        user_count = 0
        cut = 0  # default: include everything
        for i in range(len(self.history) - 1, -1, -1):
            if self.history[i][0] == "user":
                user_count += 1
                if user_count == self.WINDOW_TURNS:
                    cut = i
                    break
        # cut=0 means fewer than WINDOW_TURNS user messages — use all history.

        window = list(self.history[cut:])

        # Apply hard row cap from the tail, snapping to nearest user row.
        if len(window) > MAX_WINDOW_ROWS:
            start = len(window) - MAX_WINDOW_ROWS
            while start < len(window) and window[start][0] != "user":
                start += 1
            if start < len(window):
                window = window[start:]

        return window

    # ------------------------------------------------------------------
    # Hard trim — called immediately before every API call
    # ------------------------------------------------------------------

    def _hard_trim(self, messages: list) -> None:
        """Enforce a hard token budget by dropping oldest complete exchanges.

        An exchange is one assistant-with-tool-calls message plus all the
        tool-result messages that immediately follow it.  Always dropped
        atomically — never one message at a time — to preserve the
        invariant that every tool message has a preceding assistant tool_call.

        The exchange list is rebuilt fresh after each drop so index
        offsets are always correct.
        """
        config = lazy_import("nbchat.core.config")  # noqa: F821
        limit = int(config.CONTEXT_TOKEN_THRESHOLD * 0.85)
        # Hard cap: never keep more than this many exchanges regardless
        # of token budget — prevents the 26-drop cascade on turn rebuild.
        MAX_EXCHANGES = 16
        KEEP_RECENT_EXCHANGES = 8

        def est(msg: dict) -> int:
            content = msg.get("content") or ""
            tcs = msg.get("tool_calls") or []
            tc_text = "".join(
                tc.get("function", {}).get("arguments", "") for tc in tcs
            )
            return max(1, (len(content) + len(tc_text)) // 3)

        def total() -> int:
            return sum(est(m) for m in messages)

        def get_exchanges():
            """Rebuild exchange list from current messages state."""
            result = []
            i = 1
            while i < len(messages):
                m = messages[i]
                if m.get("role") == "assistant" and m.get("tool_calls"):
                    start = i
                    end = i + 1
                    while end < len(messages) and messages[end].get("role") == "tool":
                        end += 1
                    result.append((start, end))
                    i = end
                else:
                    i += 1
            return result

        # First pass: enforce MAX_EXCHANGES cap regardless of token count.
        # This prevents massive rebuilds from overwhelming _hard_trim.
        while True:
            exchanges = get_exchanges()
            if len(exchanges) <= MAX_EXCHANGES:
                break
            # Drop oldest exchange.
            s, e = exchanges[0]
            dropped = [messages[s+i].get("content","")[:80]
                       for i in range(1, e-s)
                       if messages[s+i].get("role") == "tool"]
            if dropped and messages[0].get("role") == "system":
                messages[0]["content"] += f"\n[earlier: {' | '.join(dropped)}]"
            _log.debug(f"_hard_trim: cap drop [{s}:{e}], exchanges={len(exchanges)}")
            del messages[s:e]

        # Second pass: drop by token budget, keeping KEEP_RECENT_EXCHANGES.
        while total() > limit:
            exchanges = get_exchanges()
            droppable = (exchanges[:-KEEP_RECENT_EXCHANGES]
                         if len(exchanges) > KEEP_RECENT_EXCHANGES else [])
            if not droppable:
                break
            s, e = droppable[0]
            dropped = [messages[s+i].get("content","")[:80]
                       for i in range(1, e-s)
                       if messages[s+i].get("role") == "tool"]
            if dropped and messages[0].get("role") == "system":
                messages[0]["content"] += f"\n[earlier: {' | '.join(dropped)}]"
            _log.debug(
                f"_hard_trim: budget drop [{s}:{e}] ({e-s} msgs),"
                f" total now {total()}"
            )
            del messages[s:e]

        # Last resort: truncate content of the largest tool result.
        while total() > limit:
            tool_indices = [
                i for i, m in enumerate(messages) if m.get("role") == "tool"
            ]
            if not tool_indices:
                break
            largest = max(
                tool_indices, key=lambda i: len(messages[i].get("content", ""))
            )
            original = messages[largest].get("content", "")
            if len(original) <= 200:
                break
            messages[largest]["content"] = (
                original[:200]
                + f"\n[...truncated {len(original)-200} chars...]"
            )
            _log.debug(f"_hard_trim: truncated [{largest}] {len(original)}->200")

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