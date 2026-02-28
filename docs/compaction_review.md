# Compaction Engine Review

This document is a high‑level code review of the *compaction* subsystem in the `nbchat` project. The review is grouped into themes (token estimation, turn grouping, core logic, integration, maintainability) and lists concrete issues, their impact, and suggested fixes.

---

## 1. Token Estimation

| Issue | Why it matters | Suggested fix |
|-------|----------------|--------------|
| Naïve `len(text)//3` heuristic | 1. Under‑estimates short messages. 2. Over‑estimates long messages. 3. Ignores role names and tool metadata that actually contribute to token usage. | • Replace with an actual tokeniser (e.g., `tiktoken` for OpenAI models).  <br>• Cache token counts per *content* and *tool_args* (already done) but also include the *role* prefix.  <br>• Provide a pluggable estimation function so the engine can be unit‑tested with a mock. |
| Repeated full‑scan in `total_tokens` | Compaction is triggered on every message – `total_tokens` walks the entire history each time, O(n).  In a long conversation this becomes the dominant cost. | • Maintain a running total that is updated incrementally when rows are added/removed.  <br>• Keep a parallel list of token counts per row to avoid recomputing. |
| Cache key is hash((content, tool_args)) | Hash collisions could mis‑estimate tokens for distinct rows.  Also, the key ignores the role and tool_id which are part of the token count. | • Use a tuple `(role, content, tool_args)` as key.  <br>• Consider a `frozenset` if order‑independent. |

## 2. Turn Grouping & Safe Split

| Issue | Why it matters | Suggested fix |
|-------|----------------|--------------|
| Hard‑coded `row[0] == "user"` to detect turn boundaries | 1. If a new role is introduced (e.g., `"assistant_partial"`), turns will be split incorrectly. 2. Legacy history that starts with a `"compacted"` row is bundled into its own group, but the logic is fragile. | • Define a set `TURN_START_ROLES = {"user", "assistant"}` and use it.  <br>• Store rows in a dataclass and access via `.role` for readability. |
| `_find_safe_split` only checks two roles | 1. It assumes the only dependent roles are `{"tool", "analysis", "assistant_full"}`. 2. If a new dependent role appears, the algorithm will incorrectly split in the middle of a tool call. | • Keep a mapping `DEPENDENT_ROLES` that is extensible.  <br>• Add unit tests that cover edge cases (e.g., consecutive `tool` rows). |
| No guard against empty or single‑row groups | If the group is one row, `i` starts at 1, leading to an `IndexError`. | • Add an explicit check: `if len(group) <= 1: return None`. |

## 3. Core Compaction Logic

| Issue | Why it matters | Suggested fix |
|-------|----------------|--------------|
| `compact_history` rebuilds the entire list of remaining turns each loop | Each iteration flattens `remaining_turns` again – O(n²) worst‑case for long histories. | • Keep a flat list of remaining rows and slice it, rather than recompute.  <br>• Use a deque for efficient popleft operations. |
| Threshold logic uses 0.75 of the hard‑coded threshold | 1. The buffer may be too large or too small depending on the LLM’s actual context window. 2. The value is buried in code rather than a config. | • Expose the buffer percentage as a config parameter (e.g., `context_buffer_percent`).  <br>• Document the rationale in the README. |
| No early exit if the *old* history is empty | Summariser call will be made on an empty list, producing nonsense. | • Add a guard: `if not older: return history`. |
| After summarisation the cache is cleared entirely | If the history is large, the cache might contain many useful entries that can be reused. | • Clear only the entries that belong to the summarised rows; or keep a small LRU cache. |
| `self.context_summary` is overwritten but never persisted | If the process restarts, the context summary is lost, causing a “summary‑in‑context” mismatch. | • Persist `context_summary` in the DB or a dedicated file.  <br>• Load it on startup in `ChatUI._load_history()`. |
| No handling of summariser failure | `RuntimeError` bubbles up and crashes the UI thread. | • Catch exceptions, log them, and fall back to no‑summary (i.e., keep the full history).  <br>• Optionally retry with a back‑off. |

## 4. Integration with `ChatUI`

| Issue | Why it matters | Suggested fix |
|-------|----------------|--------------|
| `ChatUI` calls `compact_history` synchronously in the streaming thread | If the summariser is slow, the UI thread stalls, blocking user input. | • Offload the compaction to a background thread or use asyncio.  <br>• Update the UI once the compaction completes. |
| No thread‑safety around `CompactionEngine` | `_cache_lock` protects the cache, but the rest of the engine is not guarded, so simultaneous calls could corrupt state. | • Make all public methods acquire a shared lock, or use a `threading.RLock`. |
| `ChatUI._load_history` restores only the history, not the rolling summary | `context_summary` is never loaded, so after a restart the user’s context may be wrong. | • Store `context_summary` in the DB (e.g., as a special `system` row) and load it in `_load_history`. |
| Metrics updater reads the server log in a tight loop | This thread can consume CPU and I/O; also it does not handle log rotation. | • Use a file‑watcher (e.g., `watchdog`) or sleep longer (5s) during idle periods. |
| `_refresh_tools_list` directly mutates `self.tools_output` | No separation of concerns; if tool list changes, UI will not update automatically. | • Create an observable pattern or a callback when tools change. |

## 5. Code Quality & Maintainability

| Issue | Why it matters | Suggested fix |
|-------|----------------|--------------|
| Missing type hints for many helper methods | Hard to read, static analysis fails. | • Add annotations for all functions and methods. |
| Docstrings are minimal or missing | Future contributors will struggle to understand intent. | • Add comprehensive module‑level and method‑level docstrings. |
| Hard‑coded strings (e.g., “we are running out of context window”) | Makes localisation and tweaking difficult. | • Move to a config file or constants module. |
| Hard‑coded `max_tokens=4096` | Different LLMs have different limits. | • Use `config.MAX_SUMMARY_TOKENS` or compute from model metadata. |
| No logging library | Uses `print` to `stderr`.  Hard to control verbosity. | • Replace with Python’s `logging` module. |
| No unit tests for the compaction logic | Bugs are hard to detect and regressions easy to introduce. | • Write tests that exercise: <br>  * token estimation accuracy <br>  * turn grouping <br>  * safe split <br>  * compaction on different thresholds <br>  * summariser error handling. |
| Potential memory leak in `_cache` | The cache grows unbounded if many distinct rows are seen. | • Use an `LRUCache` or prune entries that are older than a threshold. |
| Hard‑coded `tail_messages` logic | If a user wants to keep more or fewer turns, they must modify source. | • Expose as a config or allow runtime adjustment via UI. |

## 6. Suggested Refactor Skeleton

Below is a high‑level sketch of how the engine could be reorganised.  You can cherry‑pick the parts that fit your workflow.

```python
from __future__ import annotations
import threading
import logging
from collections import deque
from dataclasses import dataclass
from typing import List, Tuple, Dict, Iterable

# --------------------------------------------------------------------------- #
# 1. Row representation
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ChatRow:
    role: str
    content: str
    tool_id: str = ""
    tool_name: str = ""
    tool_args: str = ""

# --------------------------------------------------------------------------- #
# 2. Tokeniser abstraction
# --------------------------------------------------------------------------- #
class Tokeniser:
    def __init__(self, model: str):
        # Example: tiktoken.encoding_for_model(model)
        pass

    def count(self, text: str) -> int:
        # Real implementation
        return max(1, len(text) // 3)

# --------------------------------------------------------------------------- #
# 3. CompactionEngine
# --------------------------------------------------------------------------- #
class CompactionEngine:
    def __init__(self, *,
                 threshold: int,
                 tail_messages: int,
                 summary_prompt: str,
                 summary_model: str,
                 system_prompt: str,
                 tokeniser: Tokeniser | None = None):
        self.threshold = threshold
        self.tail_messages = tail_messages
        self.summary_prompt = summary_prompt
        self.summary_model = summary_model
        self.system_prompt = system_prompt
        self._tokeniser = tokeniser or Tokeniser(summary_model)

        self._lock = threading.RLock()
        self._cache: Dict[Tuple[str, str], int] = {}
        self.context_summary = ""

    # --------------------------------------------------------------------- #
    # token estimation
    # --------------------------------------------------------------------- #
    def _estimate(self, text: str) -> int:
        key = text
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            val = self._tokeniser.count(text)
            self._cache[key] = val
            return val

    def total_tokens(self, history: Iterable[ChatRow]) -> int:
        total = 0
        for row in history:
            total += self._estimate(row.content)
            if row.tool_args:
                total += self._estimate(row.tool_args)
        return total

    # --------------------------------------------------------------------- #
    # turn logic
    # --------------------------------------------------------------------- #
    TURN_START_ROLES = {"user", "assistant"}
    DEPENDENT_ROLES = {"tool", "analysis", "assistant_full"}

    @staticmethod
    def _group_into_turns(history: List[ChatRow]) -> List[List[ChatRow]]:
        turns: List[List[ChatRow]] = []
        current: List[ChatRow] = []
        for row in history:
            if row.role in CompactionEngine.TURN_START_ROLES and current:
                turns.append(current)
                current = []
            current.append(row)
        if current:
            turns.append(current)
        return turns

    @staticmethod
    def _find_safe_split(group: List[ChatRow]) -> int | None:
        if len(group) <= 1:
            return None
        for i in range(1, len(group)):
            role = group[i].role
            prev_role = group[i - 1].role
            if role not in CompactionEngine.DEPENDENT_ROLES and prev_role != "assistant_full":
                return i
        return None

    # --------------------------------------------------------------------- #
    # compaction decision
    # --------------------------------------------------------------------- #
    def should_compact(self, history: List[ChatRow]) -> bool:
        with self._lock:
            tokens = self.total_tokens(history)
        trigger = int(self.threshold * 0.75)
        logging.debug(f"tokens={tokens} trigger={trigger}")
        return tokens >= trigger

    # --------------------------------------------------------------------- #
    # main compaction routine
    # --------------------------------------------------------------------- #
    def compact_history(self, history: List[ChatRow]) -> List[ChatRow]:
        with self._lock:
            if len(history) <= self.tail_messages:
                return history

            turns = self._group_into_turns(history)
            to_summarise: List[ChatRow] = []

            remaining = deque(turns)
            # … rest of the algorithm …
```

---

**Next steps**

1. **Pick a tokeniser** – install `tiktoken` and replace the stub.  Unit tests can use a mock.  
2. **Add type hints & docstrings** – run `mypy` or `pydocstyle` to surface missing types.  
3. **Introduce logging** – replace all `print` calls with `logging`.  
4. **Persist `context_summary`** – e.g., add a `system` row to the SQLite DB.  
5. **Write tests** – at least 10 + for the core compaction logic.  

Happy hacking!