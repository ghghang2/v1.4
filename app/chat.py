# app/chat.py
"""Utilities that handle the chat logic.

The original implementation of the chat handling lived directly in
``app.py``.  Extracting the functions into this dedicated module keeps
the UI entry point small and makes the chat logic easier to unit‑test.

Functions
---------
* :func:`build_messages` – convert a conversation history into the
  list of messages expected by the OpenAI chat completion endpoint.
* :func:`stream_and_collect` – stream the assistant response while
  capturing any tool calls.
* :func:`process_tool_calls` – invoke the tools requested by the model
  and generate subsequent assistant turns.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple, Optional

import streamlit as st

from .config import MODEL_NAME
from .tools import TOOLS

# ---------------------------------------------------------------------------
#  Public helper functions
# ---------------------------------------------------------------------------

def build_messages(
    history: List[Tuple[str, str]],
    system_prompt: str,
    # repo_docs: Optional[str],
    user_input: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return the list of messages to send to the chat model.

    Parameters
    ----------
    history
        List of ``(user, assistant)`` pairs that have already happened.
    system_prompt
        The system message that sets the model behaviour.
    repo_docs
        Optional Markdown string that contains the extracted repo source.
    user_input
        The new user message that will trigger the assistant reply.
    """
    msgs: List[Dict[str, Any]] = [{"role": "system", "content": str(system_prompt)}]
    # if repo_docs:
    #     msgs.append({"role": "assistant", "content": str(repo_docs)})

    for u, a in history:
        msgs.append({"role": "user", "content": str(u)})
        msgs.append({"role": "assistant", "content": str(a)})

    if user_input is not None:
        msgs.append({"role": "user", "content": str(user_input)})

    return msgs


def stream_and_collect(
    client: Any,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    placeholder: st.delta_generator.delta_generator,
) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
    """Stream the assistant response while capturing tool calls.

    The function writes the incremental assistant content to the supplied
    Streamlit ``placeholder`` and returns a tuple of the complete
    assistant text and a list of tool calls (or ``None`` if no tool call
    was emitted).
    """
    stream = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        stream=True,
        tools=tools,
    )

    full_resp = ""
    tool_calls_buffer: Dict[int, Dict[str, Any]] = {}

    for chunk in stream:
        delta = chunk.choices[0].delta

        # Regular text
        if delta.content:
            full_resp += delta.content
            placeholder.markdown(full_resp, unsafe_allow_html=True)

        # Tool calls – accumulate arguments per call id.
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in tool_calls_buffer:
                    tool_calls_buffer[idx] = {
                        "id": tc_delta.id,
                        "name": tc_delta.function.name,
                        "arguments": "",
                    }
                if tc_delta.function.arguments:
                    tool_calls_buffer[idx]["arguments"] += tc_delta.function.arguments

    final_tool_calls = list(tool_calls_buffer.values()) if tool_calls_buffer else None
    return full_resp, final_tool_calls


def process_tool_calls(
    client: Any,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    placeholder: st.delta_generator.delta_generator,
    tool_calls: Optional[List[Dict[str, Any]]],
) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
    """
    Execute each tool that the model requested and keep asking the model
    for further replies until it stops calling tools.

    Parameters
    ----------
    client
        The OpenAI client used to stream assistant replies.
    messages
        The conversation history that will be extended with the tool‑call
        messages and the tool replies.
    tools
        The list of OpenAI‑compatible tool definitions that will be passed
        to the ``chat.completions.create`` call.
    placeholder
        Streamlit placeholder that will receive the intermediate
        assistant output.
    tool_calls
        The list of tool‑call objects produced by
        :func:`stream_and_collect`.  The function may return a new
        list of calls that the model wants to make after the tool
        result is sent back.

    Returns
    -------
    tuple
        ``(full_text, remaining_tool_calls)``.  *full_text* contains
        the cumulative assistant reply **including** the text produced
        by the tool calls.  *remaining_tool_calls* is ``None`` when the
        model finished asking for tools; otherwise it is the list of calls
        that still need to be handled.
    """
    if not tool_calls:
        return "", None

    # Accumulate all text that the assistant will eventually produce
    full_text = ""

    # We keep looping until the model stops asking for tools
    while tool_calls:
        
        for tc in tool_calls:
            
            try:
                args = json.loads(tc.get("arguments") or "{}")
            except Exception as exc:
                args = {}
                result = f"❌  JSON error: {exc}"
            else:
                
                func = next(
                    (t.func for t in TOOLS if t.name == tc.get("name")), None
                )

                if func:
                    try:
                        result = func(**args)
                    except Exception as exc:  # pragma: no cover
                        result = f"❌  Tool error: {exc}"
                else:
                    result = f"⚠️  Unknown tool '{tc.get('name')}'"
                    
            preview = result[:80] + ("…" if len(result) > 80 else "")
            full_text += (
                f"<details>"
                f"<summary>**{tc.get('name')}**: `{json.dumps(args)}`</summary>"
                f"\n\n**Result preview**: `{preview}`\n\n"
                f"</details>"
            )
            
            placeholder.markdown(full_text, unsafe_allow_html=True)
            
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tc.get("id"),
                            "type": "function",
                            "function": {
                                "name": tc.get("name"),
                                "arguments": tc.get("arguments") or "{}",
                            },
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tc.get("id") or ""),
                    "content": result,
                }
            )
            
            full_text += result
            
        new_placeholder = st.empty()
        new_text, new_tool_calls = stream_and_collect(
            client, messages, tools, new_placeholder
        )
        full_text += new_text
        
        tool_calls = new_tool_calls or None
    # placeholder.markdown(full_text, unsafe_allow_html=True)    
    return full_text
