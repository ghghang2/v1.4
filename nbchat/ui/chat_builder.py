"""Utility for converting chat history into OpenAI API message format.

This module isolates the logic that transforms the internal history
representation into a list of dictionaries suitable for the OpenAI
ChatCompletion API.

The ``context_summary`` parameter allows the compaction engine to inject a
rolling summary of older conversation turns into the system prompt without
storing a special row in the history list.  This keeps the history
append-only and avoids structural ordering constraints that previously caused
``tool``-role errors on the inference server.
"""
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
        Optional rolling summary of earlier conversation turns produced by
        the compaction engine.  When provided it is appended to the system
        prompt under a clearly labelled delimiter so the model knows it
        represents *prior* context rather than instructions.
    """
    # Build the system prompt content, appending the summary when present.
    system_content = system_prompt
    if context_summary:
        system_content = (
            f"{system_prompt}"
            "\n\n--- CONVERSATION HISTORY SUMMARY ---\n"
            f"{context_summary}"
            "\n--- END SUMMARY ---"
        )

    messages: List[Dict[str, str]] = [{"role": "system", "content": system_content}]

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
            # Legacy rows from the old compaction scheme (stored in the DB
            # before the context_summary approach was introduced).  Render
            # them as system messages so old sessions still work correctly.
            messages.append({"role": "system", "content": content})

        # "analysis" rows are reasoning traces stored for UI display only;
        # they are not sent to the model.

    return messages


__all__ = ["build_messages"]