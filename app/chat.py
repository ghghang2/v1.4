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
import logging
import time
import concurrent.futures
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from .config import MODEL_NAME
from .tools import TOOLS
from .db import log_message, log_tool_msg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    filename="chat.log",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Public helper functions
# ---------------------------------------------------------------------------

def build_messages(
    history: Any,
    system_prompt: str,
    user_input: Optional[str] = None,
    max_context_tokens: int = 60000,
) -> List[Dict[str, Any]]:
    """Return the list of messages to send to the chat model.

    Parameters
    ----------
    history
        List of ``(user, assistant, tool_id, tool_name, tool_args)``
        tuples that have already happened.
    system_prompt
        The system message that sets the model behaviour.
    user_input
        The new user message that will trigger the assistant reply.
    """
    # Estimate token usage of the conversation.  The OpenAI tokenizer is
    # complex, but for a quick heuristic we treat each word as ~4 tokens
    # (roughly the average for English).  This keeps us well below the
    # 64k token limit while still preserving recent context.
    def estimate_tokens(text: str) -> int:
        # Rough estimate: 1 token per 2 words, which is conservative for
        # English.  The goal is simply to keep the total below the
        # hard 64k token limit.
        return max(1, len(text.split())) * 2

    total_tokens = estimate_tokens(system_prompt)
    # Build a list of messages first to allow trimming.
    raw_msgs: List[Dict[str, Any]] = [{"role": "system", "content": str(system_prompt)}]
    for role, content, tool_id, tool_name, tool_args in history:
        if tool_name:
            raw_msgs.append(
                {
                    "role": role,
                    "content": "",
                    "tool_calls": [
                        {
                            "id": tool_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": tool_args or "{}",
                            },
                        }
                    ],
                }
            )
        elif role == "tool":
            raw_msgs.append({"role": role, "content": content, "tool_call_id": tool_id})
        else:
            raw_msgs.append({"role": role, "content": content})

        # Update token estimate for this message
        if role != "tool":
            total_tokens += estimate_tokens(content)
        else:
            total_tokens += estimate_tokens(content)
    if user_input is not None:
        raw_msgs.append({"role": "user", "content": str(user_input)})
        total_tokens += estimate_tokens(user_input)

    # If we still exceed the limit, drop the oldest non-system messages until
    # we are within the limit or only the system message remains.
    while total_tokens > max_context_tokens and len(raw_msgs) > 1:
        removed = raw_msgs.pop(1)
        content = removed.get("content", "")
        total_tokens -= estimate_tokens(content)

    # Additionally, cap the number of messages to avoid very long histories
    # that could still push the token count close to the limit.
    if len(raw_msgs) > 30:
        # keep system + last 29 user/assistant entries
        raw_msgs = [raw_msgs[0]] + raw_msgs[-29:]
    msgs = raw_msgs

    for role, content, tool_id, tool_name, tool_args in history:
        if tool_name:
            msgs.append(
                {
                    "role": role,
                    "content": "",
                    "tool_calls": [
                        {
                            "id": tool_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": tool_args or "{}",
                            },
                        }
                    ],
                }
            )
        elif role == "tool":
            msgs.append({"role": role, "content": content, "tool_call_id": tool_id})
        else:
            msgs.append({"role": role, "content": content})

    if user_input is not None:
        msgs.append({"role": "user", "content": str(user_input)})

    return msgs


def stream_and_collect(
    client: Any,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
) -> Tuple[str, Optional[List[Dict[str, Any]]], bool, str]:
    """Stream the assistant response while capturing tool calls.

    The function writes the incremental assistant content to a placeholder
    and returns a tuple of the complete assistant text, a list of tool
    calls (or ``None`` if no tool call was emitted), a boolean indicating
    if the assistant finished, and any reasoning text.
    """
    stream = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        stream=True,
        tools=tools,
    )

    assistant_text = ""
    reasoning_text = ""
    tool_calls_buffer: Dict[int, Dict[str, Any]] = {}
    finished = False
    reasoning_placeholder = st.empty()
    placeholder = st.empty()

    for chunk in stream:
        choice = chunk.choices[0]
        if choice.finish_reason == "stop":
            finished = True
            break
        delta = choice.delta

        if "metrics_placeholder" in st.session_state:
            st.session_state.metrics_placeholder.markdown(
                st.session_state.latest_metrics_md
            )

        reasoning_part = getattr(delta, "reasoning_content", None)
        if reasoning_part:
            reasoning_text += reasoning_part
            md = f"<details open><summary>Reasoning</summary>\n{reasoning_text}\n</details>"
            reasoning_placeholder.markdown(md, unsafe_allow_html=True)

        if delta.content:
            assistant_text += delta.content
            placeholder.markdown(assistant_text, unsafe_allow_html=True)

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
    return assistant_text, final_tool_calls, finished, reasoning_text


def process_tool_calls(
    client: Any,
    messages: List[Dict[str, Any]],
    session_id: str,
    history: List[Tuple[str, str, str, str, str]],
    tools: List[Dict[str, Any]],
    tool_calls: Optional[List[Dict[str, Any]]],
    finished: bool,
    assistant_text: str = "",
    reasoning_text: str = "",
) -> List[Tuple[str, str, str, str, str]]:
    """Execute each tool that the model requested.

    Parameters
    ----------
    client
        The OpenAI client used to stream assistant replies.
    messages
        The conversation history that will be extended with the tool‑call
        messages and the tool replies.
    session_id
        Identifier of the chat session.
    history
        Mutable list of ``(role, content, tool_id, tool_name, tool_args)``
        tuples used to build the chat history.
    tools
        The list of OpenAI‑compatible tool definitions.
    tool_calls
        The list of tool‑call objects produced by :func:`stream_and_collect`.
    finished
        Boolean indicating whether the assistant already finished a turn.
    assistant_text
        Text that the assistant returned before the first tool call.
    reasoning_text
        Any reasoning content produced by the model.

    Returns
    -------
    list
        Updated history list.
    """
    if not tool_calls:
        return history

    # Preserve any assistant text and reasoning that were produced before
    # the first tool call – the original code discarded this content.
    if assistant_text:
        history.append(("assistant", assistant_text, "", "", ""))
    if reasoning_text:
        history.append(("analysis", reasoning_text, "", "", ""))

    while tool_calls and not finished:
        for tc in tool_calls:
            try:
                args = json.loads(tc.get("arguments") or "{}")
            except Exception as exc:
                args = {}
                result = f"\u274c  JSON error: {exc}"
                logger.exception("Failed to parse tool arguments", exc_info=True)
            else:
                tool_name = tc.get("name")
                logger.info(
                    "Calling tool %s with arguments %s",
                    tool_name,
                    json.dumps(args),
                )
                func = next((t.func for t in TOOLS if t.name == tool_name), None)
                if func:
                    try:
                        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                        try:
                            if tool_name in ['browser', 'run_tests']:
                                timeout_sec = 60
                            else: 
                                timeout_sec = 30
                            future = executor.submit(func, **args)
                            result = future.result(timeout=timeout_sec)
                        except concurrent.futures.TimeoutError:  # pragma: no cover
                            result = (
                                f"\u26d4  Tool call {tool_name} timed out after {timeout_sec} seconds. "
                                "Try a shorter or more specific request."
                            )
                        except Exception as exc:  # pragma: no cover
                            result = f"\u274c  Tool error: {exc}"
                        finally:
                            executor.shutdown(wait=False)
                    except Exception as exc:  # pragma: no cover
                        result = f"\u274c  Tool error: {exc}"
                        logger.exception("Tool raised an exception", exc_info=True)
                else:
                    result = f"\u26a0\ufe0f  Unknown tool '{tc.get('name')}'"

            preview = result[:10] + ("\u2026" if len(result) > 10 else "")
            tool_block = (
                f"<details>"
                f"<summary>{tc.get('name')}|`{json.dumps(args)}`|{preview}</summary>"
                f"\n\n`{result}`\n\n"
                f"</details>"
            )
            st.empty().markdown(tool_block, unsafe_allow_html=True)

            tool_id = tc.get("id")
            
            tool_args = tc.get("arguments")
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": tool_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": tool_args or "{}",
                            },
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tool_id or ""),
                    "content": result,
                }
            )

            history.append(("assistant", "", tool_id, tool_name, tool_args))
            history.append(("tool", result, tool_id, tool_name, tool_args))

            log_tool_msg(session_id, tool_id, tool_name, tool_args, result)

        new_assistant_resp, new_tool_calls, finished, reasoning_text = stream_and_collect(
            client, messages, tools
        )

        history.append(("analysis", reasoning_text, "", "", ""))
        history.append(("assistant", new_assistant_resp, "", "", ""))
        log_message(session_id, "analysis", reasoning_text)
        log_message(session_id, "assistant", new_assistant_resp)
        tool_calls = new_tool_calls or None

    return history