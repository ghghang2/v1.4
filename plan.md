# Automatic Context Compaction Plan (Minimalist - Updated)

## 1. Overview

Automatic Context Compaction reduces chat conversation size when accumulated tokens exceed a threshold. The goal is to stay within the model's context window while preserving essential information for the agent to continue its task.

This is a **minimalist, maintainable** implementation that prioritises performance and simplicity.

---

## 2. Goals

| Feature | Description | Why |
|---------|-------------|-----|
| **Token counting** | Estimate tokens from llama-server logs (no tiktoken dependency). | Lightweight, accurate for our setup. |
| **Threshold trigger** | Compact when total tokens exceed `CONTEXT_TOKEN_THRESHOLD`. | No constant polling. |
| **Rolling tail + summary** | Keep last `TAIL_MESSAGES` verbatim, summarise older messages. | Maintain immediate context while compressing history. |
| **Minimal integration** | Leverage existing `chat_builder`, `chat_renderer`, `tool_executor`. | Fewer changes, less risk. |
| **Extensible** | Configurable threshold, tail length, summary prompt. | Adapt to different use cases. |

---

## 3. Architecture

```
+---------------------+       +-----------------------+       +-----------------+
|    ChatUI (UI)     |       |  CompactionEngine    |       |   Assistant     |
+---------------------+       +-----------------------+       +-----------------+
         |                              |                             |
         |   token_count, threshold     |                             |
         |------------------------------|                             |
         |                              |                             |
         |   should_compact?            |                             |
         |------------------------------|                             |
         |                              |                             |
         |   compact_history()          |                             |
         |------------------------------|                             |
         |   [older messages]           |                             |
         |------------------------------|                             |
         |                              |   summary request           |
         |                              |---------------------------->|
         |                              |   summary response          |
         |                              |<----------------------------|
         |   new_history =              |                             |
         |     summary + tail           |                             |
         |<-----------------------------|                             |
```

* **CompactionEngine** – New module with token counting, threshold checking, and summarisation logic.
* **TokenTracker** – Helper to parse llama-server logs for token counts and cache per-message estimates.
* **Config** – Add `CONTEXT_TOKEN_THRESHOLD`, `TAIL_MESSAGES`, `SUMMARY_PROMPT` to `config.py`.

---

## 4. Key Components

### 4.1 TokenTracker (New Helper)

```python
# nbchat/compaction.py - TokenTracker class
import re
from pathlib import Path
from typing import Dict, Optional

class TokenTracker:
    """Tracks token counts by parsing llama-server logs and caching per message."""
    
    def __init__(self):
        self.message_tokens: Dict[int, int] = {}  # message index -> token count estimate
        self.total_tokens = 0
        
    def estimate_tokens(self, text: str) -> int:
        """Simple token estimation: ~4 chars per token."""
        return max(1, len(text) // 4)
    
    def update_from_log(self, log_path: Path = Path("llama_server.log")):
        """Parse llama-server log for recent token counts.
        
        Log lines contain: 'task.n_tokens = 55221' or 'n_tokens = 56063'
        We track the most recent total to calibrate our estimates.
        """
        if not log_path.exists():
            return
        
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 10000))  # last 10KB
            content = f.read().decode("utf-8", errors="ignore")
            
        # Find most recent token count from log
        pattern = r'task\.n_tokens\s*=\s*(\d+)'
        matches = re.findall(pattern, content)
        if matches:
            # Use average of recent counts for calibration
            recent_counts = [int(m) for m in matches[-5:]]  # last 5
            avg_actual = sum(recent_counts) / len(recent_counts)
            # TODO: Compare with our estimate and adjust factor
```

### 4.2 CompactionEngine

```python
# nbchat/compaction.py
from typing import List, Tuple, Optional
from nbchat.ui.chat_builder import build_messages
from nbchat.core.client import get_client

class CompactionEngine:
    def __init__(self, threshold: int, tail_messages: int = 5, 
                 summary_prompt: str = None, summary_model: str = None,
                 system_prompt: str = ""):
        self.threshold = threshold
        self.tail_messages = tail_messages
        self.summary_prompt = summary_prompt or (
            "Summarize the conversation so far, focusing on: "
            "1. Key decisions made\n"
            "2. Important file paths and edits\n"
            "3. Tool calls and their outcomes (summarize large outputs)\n"
            "4. Next steps planned\n"
            "Keep it concise but preserve teach-a-man-to-fish information."
        )
        self.summary_model = summary_model
        self.system_prompt = system_prompt
        self.token_tracker = TokenTracker()
        
    def total_tokens(self, history: List[Tuple[str, str, str, str, str]]) -> int:
        """Calculate total tokens in history using cached estimates."""
        total = 0
        for i, (role, content, tool_id, tool_name, tool_args) in enumerate(history):
            if i in self.token_tracker.message_tokens:
                total += self.token_tracker.message_tokens[i]
            else:
                # Estimate and cache
                msg_tokens = self.token_tracker.estimate_tokens(content)
                if tool_args:
                    msg_tokens += self.token_tracker.estimate_tokens(tool_args)
                self.token_tracker.message_tokens[i] = msg_tokens
                total += msg_tokens
        return total
    
    def should_compact(self, history: List[Tuple[str, str, str, str, str]]) -> bool:
        """Check if history exceeds token threshold."""
        return self.total_tokens(history) >= self.threshold
    
    def compact_history(self, history: List[Tuple[str, str, str, str, str]]) -> List[Tuple[str, str, str, str, str]]:
        """Summarise older messages, keep recent tail.
        
        Returns new history or raises exception on failure.
        """
        if len(history) <= self.tail_messages:
            return history  # Not enough to compact
        
        older = history[:-self.tail_messages]
        tail = history[-self.tail_messages:]
        
        # Build messages for summarisation with original system prompt
        messages = build_messages(older, self.system_prompt)
        messages.append({"role": "user", "content": self.summary_prompt})
        
        # Request summary - must succeed or raise
        client = get_client()
        try:
            response = client.chat.completions.create(
                model=self.summary_model or "gpt-4",
                messages=messages,
                max_tokens=512,
            )
        except Exception as e:
            raise RuntimeError(f"Summarization failed: {e}")
        
        summary_text = response.choices[0].message.content
        
        # New history: summary (as system message) + tail
        # Use role "system" for API compatibility
        return [("system", summary_text, "", "", "")] + tail
```

### 4.3 Integration with ChatUI

In `ChatUI._process_conversation_turn`, after each assistant response:

```python
# After receiving assistant response
if self.compaction_engine.should_compact(self.history):
    try:
        new_history = self.compaction_engine.compact_history(self.history)
        with self._history_lock:
            # Update history and UI
            self.history = new_history
            
            # Delete old messages from database
            db = lazy_import("nbchat.core.db")
            # We'll need a function to delete messages for a session
            # db.delete_messages_except(self.session_id, new_history)
            
            self._render_history()  # Update UI
    except Exception as e:
        # Log error but continue conversation without compaction
        print(f"Compaction failed: {e}")
```

### 4.4 Configuration

Add to `nbchat/core/config.py`:

```python
# Context compaction defaults
CONTEXT_TOKEN_THRESHOLD = 5000
TAIL_MESSAGES = 5
SUMMARY_PROMPT = (
    "Summarize the conversation so far, focusing on:\n"
    "1. Key decisions made\n"
    "2. Important file paths and edits\n"
    "3. Tool calls and their outcomes (summarize large outputs)\n"
    "4. Next steps planned\n"
    "Keep it concise but preserve teach-a-man-to-fish information."
)
```

Update `ChatUI.__init__`:

```python
from nbchat.core.config import (
    CONTEXT_TOKEN_THRESHOLD, 
    TAIL_MESSAGES, 
    SUMMARY_PROMPT,
    MODEL_NAME,
    DEFAULT_SYSTEM_PROMPT
)
self.compaction_engine = CompactionEngine(
    threshold=CONTEXT_TOKEN_THRESHOLD,
    tail_messages=TAIL_MESSAGES,
    summary_prompt=SUMMARY_PROMPT,
    summary_model=MODEL_NAME,
    system_prompt=DEFAULT_SYSTEM_PROMPT,
)
```

### 4.5 UI and Database Updates

* **chat_renderer.py**: Add `render_system_summary()` for compacted summary messages.
* **chat_builder.py**: "system" role messages already handled.
* **db.py**: Add `delete_messages_except(session_id, keep_indices)` to remove old messages after compaction.

---

## 5. Token Counting Strategy

Use **llama-server log parsing** + **cached estimates**:
- Parse `llama_server.log` for `task.n_tokens = X` to get actual token counts
- Cache token estimates per message (simple char/4 heuristic)
- Calibrate heuristic against actual log values periodically
- Avoid tiktoken dependency

**Performance**: Cached estimates make `total_tokens()` O(1) for unchanged history.

---

## 6. History Management

After compaction:
1. Older messages → single system message with summary
2. Last `TAIL_MESSAGES` messages kept verbatim
3. Old messages deleted from database
4. Summary appears before tail in history

**Example**: 10 messages, TAIL_MESSAGES=5
- Messages 1-5 → summarised into system message
- Messages 6-10 → kept verbatim
- Database: Delete rows for messages 1-5
- Result: [system_summary, msg6, msg7, msg8, msg9, msg10]

---

## 7. Testing Strategy

| Test | Description |
|------|-------------|
| `test_token_tracker` | Verify log parsing and estimation calibration. |
| `test_should_compact` | Test threshold detection with various histories. |
| `test_compact_history` | Mock API call, verify summary + tail structure. |
| `test_db_cleanup` | Verify old messages deleted, summary stored. |
| `test_integration` | End-to-end with low threshold, ensure UI updates. |
| `test_failure_handling` | Simulate API failure, ensure conversation continues. |

Use `pytest` with mocked API client and in-memory database.

---

## 8. Deployment Notes

* No new dependencies (no tiktoken)
* Backward compatible: compaction disabled without configuration
* Summary messages appear as system messages in UI (distinct styling)
* Database cleanup prevents bloat
* Thread-safe: uses existing `_history_lock`

---

## 9. Future Enhancements (Optional)

1. **Incremental compaction**: Summarise long tool outputs immediately.
2. **Dynamic thresholds**: Adjust based on model context window.
3. **Cheaper summary model**: Use smaller/cheaper model for summarisation.
4. **Case file extraction**: Extract key file paths, decisions to separate structure.

---

## 10. Implementation Checklist

- [ ] Create `TokenTracker` class with log parsing
- [ ] Create `CompactionEngine` class
- [ ] Add configuration to `config.py`
- [ ] Integrate into `ChatUI._process_conversation_turn`
- [ ] Add `delete_messages_except()` to `db.py`
- [ ] Add `render_system_summary()` to `chat_renderer.py`
- [ ] Update UI styling for summary messages
- [ ] Write comprehensive tests
- [ ] Document new configuration options

---

*End of updated minimalist plan.*