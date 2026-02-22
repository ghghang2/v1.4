# Automatic Context Compaction Plan

## 1. Overview

Automatic Context Compaction is the process of reducing a chat conversation to a compact summary once the accumulated token usage reaches a configurable threshold.  The goal is to keep the conversation **within the model’s context window** while still preserving the information that is needed for the agent to continue its task.

This plan outlines a lightweight implementation that can be dropped into the existing `nbchat` repository without major refactors.

---

## 2. Goals

| Feature | Description | Why |
|---------|-------------|-----|
| **Token‑aware history** | Count tokens per turn and keep a running total. | Detect when we exceed the limit. |
| **Trigger‑based compaction** | When the total exceeds `context_token_threshold`, start the compaction process. | No constant polling; only when necessary. |
| **Summarization** | Ask Claude to produce a short summary of the conversation so far. | Keep only essential data. |
| **History replacement** | Replace the entire message list with the summary message. | Reset token budget. |
| **Non‑intrusive** | Use existing APIs (`chat_builder`, `chat_renderer`, `tool_executor`). | Minimal changes to core logic. |
| **Extensible** | Allow custom summary prompts and optional summary model. | Future use‑cases. |

---

## 3. Architecture

```
+-------------------+          +-----------------+          +-----------------+
|  ChatUI (UI)     |   ⇄      |  ChatRunner     |   ⇄      |  OpenAI/Claude |
+-------------------+          +-----------------+          +-----------------+
        |                           |                          |
        |   token_count, threshold   |                          |
        |---------------------------|                          |
        |                           |                          |
        |   trigger_compaction()    |                          |
        |---------------------------|                          |
        |   build_summary_request() |                          |
        |---------------------------|                          |
        |   send_summary_to_model() |                          |
        |---------------------------|                          |
        |   replace_history()       |                          |
        |---------------------------|                          |
```

* **ChatRunner** – a thin wrapper around the existing logic in `ChatUI._process_conversation_turn`.  It will be extended to keep track of token usage and decide when to compact.
* **CompactionEngine** – a new module containing the core logic (token counter, trigger, summary request, history replacement).
* **Config** – add `context_token_threshold` and optional `summary_prompt` to `config.py`.

---

## 4. Key Components

### 4.1 CompactionEngine

```python
# nbchat/compaction.py
from typing import List, Tuple
from nbchat.ui.chat_builder import build_messages
from nbchat.core.client import get_client

class CompactionEngine:
    def __init__(self, threshold: int, summary_prompt: str | None = None, summary_model: str | None = None):
        self.threshold = threshold
        self.summary_prompt = summary_prompt or "Summarize the conversation so far."
        self.summary_model = summary_model
        self.input_tokens = 0

    def update_token_count(self, message: dict, usage: dict):
        """Add the input token count for a single assistant response.
        The caller passes the raw message dict and the usage dict from the API.
        """
        self.input_tokens += usage.get("input_tokens", 0)

    def should_compact(self) -> bool:
        return self.input_tokens >= self.threshold

    def create_summary_request(self, history: List[Tuple[str, str, str, str, str]]) -> dict:
        """Return a user message that asks the model to summarize the current history.
        The summary will be wrapped in `<summary></summary>` tags.
        """
        summary_msg = f"{self.summary_prompt}"
        return {"role": "user", "content": summary_msg}

    def replace_history(self, messages: List[dict]) -> List[dict]:
        """Replace all but the last user message with the summary.
        The summary message is expected to be the last element in *messages*.
        """
        summary = messages[-1]
        return [summary]
```

### 4.2 Integration with ChatUI

In `ChatUI._process_conversation_turn`, after each assistant turn we:

1. Call `compaction_engine.update_token_count(msg, usage)`.
2. If `compaction_engine.should_compact()`:
   * Build a summary request: `summary_msg = compaction_engine.create_summary_request(self.history)`.
   * Send it to the model **without** the rest of the history.
   * Receive the summary response and store it as a single message.
   * Replace the current history with `[summary_msg]` via `compaction_engine.replace_history(messages)`.
   * Reset `compaction_engine.input_tokens` to 0.

**Code Snippet** (inside `_process_conversation_turn` loop):

```python
# After receiving an assistant response
if self.compaction_engine.should_compact():
    # 1. Build summary request
    summary_msg = self.compaction_engine.create_summary_request(self.history)
    # 2. Send request (no history)
    summary_resp = client.chat.completions.create(
        model=self.compaction_engine.summary_model or self.model_name,
        messages=[summary_msg],
        max_tokens=512,
    )
    # 3. Store summary
    summary_text = summary_resp.choices[0].message.content
    self.history = [("assistant", summary_text, "", "", "")]
    # 4. Reset counter
    self.compaction_engine.input_tokens = 0
```

### 4.3 Configuration

Add to `nbchat/core/config.py`:

```python
# Context compaction defaults
CONTEXT_TOKEN_THRESHOLD = 5000
SUMMARY_PROMPT = (
    "Please summarize the conversation so far in a concise format, "
    "including processed tickets, categories, priorities, and next steps."
)
SUMMARY_MODEL = "claude-haiku-4-5"  # optional, defaults to current model
```

Expose these in `ChatUI` initialization:

```python
from nbchat.core.config import (
    CONTEXT_TOKEN_THRESHOLD,
    SUMMARY_PROMPT,
    SUMMARY_MODEL,
)
self.compaction_engine = CompactionEngine(
    threshold=CONTEXT_TOKEN_THRESHOLD,
    summary_prompt=SUMMARY_PROMPT,
    summary_model=SUMMARY_MODEL,
)
```

---

## 5. Token Counting Strategy

* We use the `usage` object returned by the OpenAI/Claude SDK for each response.
* `usage.input_tokens` represents the number of tokens sent *in that single request*, **including** the entire conversation history that was sent.
* Since we only care about the *total* tokens sent so far, we simply accumulate `usage.input_tokens` after each assistant turn.
* Reset the counter after a compaction.

If the SDK exposes `usage.output_tokens`, we ignore it for compaction purposes because output tokens do not contribute to the next request’s cost.

---

## 6. Summary Generation

* The summary prompt is simple; it can be overridden by the user.
* The model should wrap the summary in `<summary></summary>` tags.  The UI can strip these tags before displaying.
* We set a relatively small `max_tokens` (e.g., 512) to keep the summary concise.

---

## 7. History Replacement

* The conversation history is represented in `ChatUI.history` as a list of tuples `(role, content, tool_id, tool_name, tool_args)`.
* After compaction we replace the entire list with a single entry: `("assistant", summary_text, "", "", "")`.
* Subsequent turns will build on this single message.
* The `chat_builder.build_messages` function will naturally handle this history format.

---

## 8. Testing Strategy

| Test | Description |
|------|-------------|
| `test_compaction_engine` | Instantiate engine with low threshold, feed tokens, verify `should_compact()` toggles correctly. |
| `test_summary_request` | Mock the client to return a pre‑defined summary; ensure history is replaced. |
| `test_integration` | Run a short ticket‑processing flow with `context_token_threshold=200` to trigger compaction early; verify the final history contains a summary message. |
| `test_no_compaction` | Set threshold very high; ensure no compaction occurs. |

Use `pytest` and `unittest.mock` to patch the client.

---

## 9. Deployment Notes

* No changes to the server side or external services are required.
* The compaction logic runs entirely on the client side, using the same OpenAI/Claude API that the rest of the chat uses.
* The UI will show a short *“Compaction occurred”* message or similar indicator for debugging.

---

## 10. Future Enhancements

1. **Server‑side compaction** – move the logic into the LLM server to avoid an extra round‑trip.
2. **Dynamic threshold** – adjust threshold based on current model context size.
3. **Custom summarization models** – allow a cheaper model for the summary step.
4. **Persist summaries** – store the summary in the DB for audit trails.

---

*End of plan.*
