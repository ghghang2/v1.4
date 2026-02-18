"""Utility for converting chat history into OpenAI API message format.

This module isolates the logic that transforms the internal history
representation into a list of dictionaries suitable for the OpenAI
ChatCompletion API.  The original implementation lived inside
``ChatUI._build_messages_for_api``; moving it here makes the intent
clearer and allows other parts of the code base to reuse the
functionality.
"""

from __future__ import annotations

import json
from typing import List, Dict, Tuple

def build_messages(history: List[Tuple[str, str, str, str, str]], system_prompt: str) -> List[Dict[str, str]]:
    """Build OpenAI messages from internal chat history.

    Parameters
    ----------
    history:
        List of tuples ``(role, content, tool_id, tool_name, tool_args)``.
    system_prompt:
        The system message to prepend.
    """

    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
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
        elif role == "tool":
            messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": content,
            })
    return messages

__all__ = ["build_messages"]
