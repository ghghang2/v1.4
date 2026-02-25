# Compaction Engine – Technical Design Document

## 1. Purpose
The **compaction** subsystem keeps the chat history that is sent to the LLM within a user‑defined token budget.  When the history grows too large, older turns are replaced with a single *compacted* system message containing a concise summary of the discarded portion.

The subsystem is composed of two main parts:

* `CompactionEngine` (in `nbchat/compaction.py`) – a pure‑Python helper that estimates token usage, decides when to compact, and performs the compaction.
* The integration in `ChatUI` (in `nbchat/ui/chatui.py`) – the UI layer that calls the engine, updates the database and the widget tree.

Below is a step‑by‑step walkthrough of the current implementation.

---

## 2. Core Concepts
| Term | Meaning |
|------|---------|
| **History** | List of tuples `(role, content, tool_id, tool_name, tool_args)`.  Roles are: `user`, `assistant`, `analysis`, `assistant_full`, `tool`, `system`, `compacted`.
| **Token estimate** | Rough count of LLM tokens.  Implemented as `len(text)//3`.  It is *not* a perfect measurement but works well for the 20B model used in this repo.
| **Threshold** | Maximum tokens before compaction is considered.  Configured via `config.CONTEXT_TOKEN_THRESHOLD`.
| **Tail messages** | The most recent `TAIL_MESSAGES` turns that are left untouched during compaction.  Configured via `config.TAIL_MESSAGES`.
| **Compacted row** | A system‑role message containing a summary of the discarded history.  It appears as a single row in the DB and the UI.

---

## 3. `CompactionEngine`
### 3.1  Constructor
```python
CompactionEngine(
    threshold: int,
    tail_messages: int = 5,
    summary_prompt: str | None = None,
    summary_model: str | None = None,
    system_prompt: str = ""
)
```
* `threshold` – token budget.
* `tail_messages` – how many recent turns to keep verbatim.
* `summary_prompt` – prompt passed to the summariser.  If `None`, a default is used (see the class docstring).
* `summary_model` – name of the model used for summarisation.  Defaults to the main model.
* `system_prompt` – system message passed to `build_messages` when summarising older history.

The constructor also creates a thread‑safe cache (`self._cache`) keyed by `(content, tool_args)` to avoid recomputing token estimates for identical rows.

---

### 3.2  Token Estimation
```python
_estimate_tokens(text: str) -> int
```
A simple heuristic: `max(1, len(text)//3)`.  The function is intentionally lightweight.

```python
total_tokens(history) -> int
```
Iterates over all history rows, sums the estimate of `content` and, if present, `tool_args`.  Results are cached.

---

### 3.3  Decision Logic – `should_compact`
```python
def should_compact(history) -> bool:
```
1. **Early exit** – if the history already starts with a `compacted` row *and* the length is `<= tail_messages + 1` (i.e. only a compacted row + tail), compaction is skipped to avoid infinite loops.
2. **Token check** – compute `tokens = total_tokens(history)` and compare against `trigger = int(threshold * 0.75)`.  The factor 0.75 gives a small buffer before compaction.
3. Logs the estimate to `stderr` for debugging.

If `tokens >= trigger`, the method returns `True`.

---

### 3.4  Performing Compaction – `compact_history`
```python
def compact_history(history) -> List[Tuple]
```
The core algorithm:

1. **Guard** – if `len(history) <= tail_messages`, no compaction.
2. **Identify split point** – start at `len(history) - tail_messages`.  Move backwards until a `user` role is found.  This guarantees the tail starts at a logical turn boundary, complying with the llama‑cpp Jinja template that expects a `tool` result to be preceded by an assistant message with a tool call.
3. **Validate** – if no boundary is found or the older slice is less than two rows, skip compaction.
4. **Slice** – `older = history[:tail_start]`, `tail = history[tail_start:]`.
5. **Build messages for summariser** – call `build_messages(older, system_prompt)` which converts the older part into a list of OpenAI‑style messages.
6. **Clean up** – remove the `reasoning_content` field from each message; it is an output‑only field that would confuse the summariser.
7. **Add summarisation instruction** – append a user‑role message containing `summary_prompt`.
8. **Call the summariser** – use `get_client().chat.completions.create(...)` with `max_tokens=4096`.
9. **Handle failure** – raise `RuntimeError` if the summarisation request fails.
10. **Clear token cache** – because the history shape changed.
11. **Return new history** – a single `compacted` row followed by the tail.

```python
return [("compacted", summary_text, "", "", "")] + list(tail)
```

The returned list contains the new history that will replace the old one.

---

## 4. Integration with `ChatUI`
`ChatUI` is the Jupyter‑widget interface that manages user interaction and streaming.  Compaction is invoked *synchronously* inside the streaming thread so that the next API call always contains a history that respects the token limit.

### 4.1  Key Methods

| Method | Purpose |
|--------|---------|
| `_compact_now(messages)` | Called after a normal assistant reply or after a tool round‑trip.  It:
| | 1. Checks `should_compact`.
| | 2. If compaction is needed, calls `compact_history`.
| | 3. Updates `self.history` and the DB (`db.replace_session_history`).
| | 4. Rebuilds the `messages` list that will be sent next.
| | 5. Renders the compacted summary in the UI.
| | 6. Returns `True` if compaction occurred.
| `_process_conversation_turn` | Main loop that sends messages, streams replies, handles tool calls, and calls `_compact_now` after each turn.
| | It ensures that the next outgoing request already contains the compacted context.

### 4.2  Flow Summary
```
1. User sends a message.
2. UI appends the user row to history.
3. Stream thread starts and builds `messages` via `build_messages(history, system_prompt)`.
4. For each turn:
   a. Call the LLM.
   b. Stream response, rendering reasoning, assistant text, tool calls.
   c. After a plain assistant reply or after finishing a tool round‑trip, invoke `_compact_now(messages)`.
   d. `_compact_now` may replace the history with a compacted version.
   e. The updated `messages` list is used for the *next* LLM call.
5. Loop until the reply is complete or max tool turns reached.
```

Because `_compact_now` runs in the same thread as the stream, the UI sees the compacted summary immediately, and the subsequent API call never exceeds the configured token threshold.

---

## 5. Configuration Overview
| Setting | Default | Meaning |
|---------|---------|---------|
| `CONTEXT_TOKEN_THRESHOLD` | 10,000 | Maximum tokens allowed for a conversation. |
| `TAIL_MESSAGES` | 4 | Number of recent turns preserved verbatim. |
| `SUMMARY_PROMPT` | *multi‑line prompt* | Instruction given to the summariser. |
| `MODEL_NAME` | `