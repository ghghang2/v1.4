"""Utility for converting chat history into OpenAI API message format."""
from __future__ import annotations

import json
from typing import List, Dict, Tuple


def build_messages(
    history: List[Tuple[str, str, str, str, str]],
    system_prompt: str,
    context_summary: str = "",
) -> List[Dict[str, str]]:
    """Build OpenAI messages from internal chat history.

    Parameters
    ----------
    history:
        List of tuples ``(role, content, tool_id, tool_name, tool_args)``.
    system_prompt:
        The system message to prepend.
    context_summary:
        Rolling summary produced by CompactionEngine.  When non-empty it is
        injected as a second system message immediately after the main system
        prompt so the model always has the prior context even after rows have
        been dropped from history.
    """
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]

    # Inject the rolling compaction summary right after the system prompt.
    if context_summary:
        messages.append({
            "role": "system",
            "content": (
                "Summary of the conversation so far (before the messages below):\n"
                + context_summary
            ),
        })

    for role, content, tool_id, tool_name, tool_args in history:
        if role == "user":
            messages.append({"role": "user", "content": content})
        elif role == "assistant":
            if tool_id:
                messages.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": tool_id,
                            "type": "function",
                            "function": {"name": tool_name, "arguments": tool_args},
                        }
                    ],
                })
            else:
                messages.append({"role": "assistant", "content": content})
        elif role == "assistant_full":
            try:
                full_msg = json.loads(tool_args)
                messages.append(full_msg)
            except Exception:
                messages.append({"role": "assistant", "content": content})
        elif role == "system":
            messages.append({"role": "system", "content": content})
        elif role == "tool":
            messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": content,
            })
        elif role == "compacted":
            # Legacy rows from old sessions — surface as a system message.
            messages.append({"role": "system", "content": content})

    return messages


__all__ = ["build_messages"]