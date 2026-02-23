# Automatic Context Compaction Plan (Simplified Minimalist)

## 1. Overview

Automatic Context Compaction reduces chat conversation size when accumulated tokens exceed a threshold. The goal is to stay within the model's context window while preserving the information needed for the agent to continue its task.

**Minimalist, maintainable, performance-focused.**

---

## 2. Goals

| Feature | Description | Why |
|---------|-------------|-----|
| **Simple token counting** | Character-based estimation (~4 chars/token). | No dependencies, good enough for threshold detection. |
| **Threshold trigger** | Compact when total tokens exceed `CONTEXT_TOKEN_THRESHOLD`. | No constant polling. |
| **Rolling tail + summary** | Keep last `TAIL_MESSAGES` verbatim, summarise older messages. | Maintain immediate context while compressing history. |
| **Minimal integration** | Leverage existing `chat_builder`, `chat_renderer`, `tool_executor`. | Fewer changes, less risk. |
| **Configurable** | Adjust threshold, tail length, summary prompt. | Adapt to different use cases. |

---

## 3. Core Architecture

### CompactionEngine (new module)
- Token counting with simple caching
- Threshold checking
- Summarization request handler
- Thread-safe design

### Integration Points
1. **Config**: Add `CONTEXT_TOKEN_THRESHOLD`, `TAIL_MESSAGES`, `SUMMARY_PROMPT`
2. **ChatUI**: Call compaction after each assistant response
3. **UI**: Distinct styling for compacted summaries
4. **DB**: No schema changes; all messages preserved

---

## 4. Implementation Summary

### 4.1 Token Counting
```python
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)  # ~4 chars per token
```
- Cache per message using content hash
- Clear cache after compaction
- Thread-safe with locks

### 4.2 Compaction Logic
1. Split history: older messages vs. tail (last N)
2. Send older messages + summary prompt to model
3. Receive summary, create system message
4. New history = [system_summary] + tail

### 4.3 Integration
```python
# In ChatUI._process_conversation_turn
if self.history and self.compaction_engine.should_compact(self.history):
    new_history = self.compaction_engine.compact_history(self.history)
    with self._history_lock:
        self.history = new_history
        self._render_history()
```

### 4.4 Configuration (`config.py`)
```python
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

### 4.5 UI Updates
- `render_compacted_summary()` in `chat_renderer.py`
- Collapsed section labeled "Compacted earlier conversation"
- Distinct visual styling

---

## 5. Why This Works

1. **Simple token estimation** is sufficient for threshold detection
2. **Rolling tail** maintains immediate task context
3. **System message summary** preserves API compatibility
4. **No database changes** keeps implementation simple
5. **Thread-safe** uses existing locking patterns

---

## 6. Trade-offs Accepted

- **Token accuracy**: Approximate (char/4) vs. exact (tiktoken)
- **Database bloat**: Keep all messages vs. delete old ones
- **Summary quality**: Generic prompt vs. task-specific tuning
- **Performance**: Cached estimates vs. real-time counting

---

## 7. Implementation Checklist

- [ ] `nbchat/compaction.py`: Create `CompactionEngine` class
- [ ] `nbchat/core/config.py`: Add compaction constants
- [ ] `nbchat/ui/chatui.py`: Integrate into conversation loop
- [ ] `nbchat/ui/chat_renderer.py`: Add `render_compacted_summary()`
- [ ] Tests: Token estimation, threshold detection, integration
- [ ] Documentation: Update README with configuration options

---

## 8. Future Extensions (If Needed)

1. **Incremental compaction**: Summarize long tool outputs immediately
2. **Dynamic thresholds**: Percentage of model context window
3. **Cheaper summary model**: Smaller model for summarization
4. **Database archiving**: `archived` flag for old messages

---

*Plan complete. Ready for implementation.*