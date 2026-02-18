from __future__ import annotations

import ipywidgets as widgets
import json
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import markdown  # for markdown rendering
from IPython.display import display

from nbchat.ui import styles
from nbchat.core.utils import lazy_import, md_to_html
# Import changed_files from metrics_ui to display list of changed files
try:
    from app.metrics_ui import changed_files  # type: ignore
except Exception:  # pragma: no cover - fallback if import fails
    changed_files = lambda: []

class ChatUI:
    """Chat interface with streaming, reasoning, and safe tool execution."""

    MAX_TOOL_TURNS = 50

    def __init__(self):
        db = lazy_import("nbchat.core.db")
        db.init_db()

        config = lazy_import("nbchat.core.config")
        self.default_system_prompt = config.DEFAULT_SYSTEM_PROMPT
        self.model_name = config.MODEL_NAME

        self.session_id = str(uuid.uuid4())
        # history: (role, content, tool_id, tool_name, tool_args)
        # role can be: "user", "assistant", "analysis", "tool", "assistant_full"
        self.history: List[Tuple[str, str, str, str, str]] = []
        self.system_prompt = self.default_system_prompt

        self.session_ids = db.get_session_ids()

        self._create_widgets()
        self._start_metrics_updater()
        self._load_history()
        display(self.layout)

    # ------------------------------------------------------------------
    # Widget creation
    # ------------------------------------------------------------------
    def _create_widgets(self):
        """Create all ipywidgets components."""
        # ----- Sidebar -----
        self.metrics_output = widgets.HTML(
            value="<i>Loading server status...</i>",
            layout=widgets.Layout(width="100%", border="1px solid gray", padding="10px")
        )

        self.new_chat_btn = widgets.Button(
            description="New Chat",
            button_style="primary",
            layout=widgets.Layout(width="100%")
        )
        self.new_chat_btn.on_click(self._on_new_chat)

        # Tools list
        self.tools_output = widgets.HTML(
            value="<b>Tools</b><br>",
            layout=widgets.Layout(width="100%", border="1px solid lightgray", padding="2px")
        )
        self._update_tools_list()

        # Session selector
        options = list(self.session_ids)
        if self.session_id not in options:
            options.append(self.session_id)
        self.session_dropdown = widgets.Dropdown(
            options=options,
            value=self.session_id,
            description="id",
            layout=widgets.Layout(width="100%")
        )
        self.session_dropdown.observe(self._on_session_change, names="value")

        sidebar = widgets.VBox([
            widgets.HTML("<h3>Chat Controls</h3>"),
            self.metrics_output,
            widgets.HTML("<hr>"),
            self.new_chat_btn,
            widgets.HTML("<hr>"),
            self.tools_output,
            widgets.HTML("<hr>"),
            self.session_dropdown,
        ], layout=widgets.Layout(width="15%", border="1px solid lightgray", padding="2px"))

        # ----- Main area -----
        self.chat_history = widgets.VBox(
            [],
            layout=widgets.Layout(
                width="100%",
                height="400px",
                overflow_y="auto",
                border="1px solid #ccc",
                padding="5px"  # reduced padding
            )
        )

        # Use a Textarea instead of Text to enable word wrapping and multiline input.
        self.input_text = widgets.Textarea(
            placeholder="...",
            layout=widgets.Layout(width="90%", height="80px"),
            rows=2,
            # The Textarea widget automatically wraps text.
        )
        self.send_btn = widgets.Button(
            description="Send",
            button_style="success",
            layout=widgets.Layout(width="5%", margin_left="1%")
        )
        self.input_box = widgets.HBox([self.input_text, self.send_btn])

        # Textarea does not support on_submit; use the Send button only.
        self.send_btn.on_click(self._on_send)

        main = widgets.VBox([
            widgets.HTML(""),
            self.chat_history,
            self.input_box,
        ], layout=widgets.Layout(width="100%", padding="0px"))

        # Overall layout
        self.layout = widgets.HBox([sidebar, main])

    def _update_tools_list(self):
        tools = lazy_import("nbchat.tools")
        tools_list = "<br>".join([tool["function"]["name"] for tool in tools])
        self.tools_output.value = f"<b>Tools</b><br>{tools_list}"

    # ------------------------------------------------------------------
    # Metrics updater
    # ------------------------------------------------------------------
    def _start_metrics_updater(self):
        """Background thread to update server metrics."""
        def update_loop():
            while True:
                try:
                    log_path = Path("llama_server.log")
                    if log_path.exists():
                        with open(log_path, "rb") as f:
                            f.seek(0, 2)
                            f.seek(max(0, f.tell() - 4000))
                            lines = f.read().decode("utf-8", errors="ignore").splitlines()
                        proc = any("slot update_slots:" in l.lower() for l in lines[-10:])
                        if any("all slots are idle" in l.lower() for l in lines[-5:]):
                            proc = False
                        tps = 0.0
                        for line in reversed(lines):
                            if "eval time" in line.lower():
                                m = re.search(r"(?P<value>\d+(?:\.\d+)?)\s+tokens per second", line, re.IGNORECASE)
                                if m:
                                    tps = float(m.group("value"))
                                    break
                        emoji = "🟢" if proc else "⚫"
                        content = f"<b>Server</b> {emoji}<br><b>TPS:</b> <code>{tps}</code><br><i>{time.strftime('%H:%M:%S')}</i>"
                        # Append list of changed files to the metrics display
                        try:
                            changed_files_list = changed_files()
                        except Exception as e:
                            changed_files_list = [f"Error retrieving changed files: {e}"]
                        if changed_files_list:
                            content += "<br><br><b>Changed files:</b><br>" + "<br>".join(changed_files_list)
                    else:
                        content = "<i>Log file not found</i>"
                except Exception as e:
                    content = f"<i>Error {e}</i>"

                self.metrics_output.value = content
                time.sleep(1)

        thread = threading.Thread(target=update_loop, daemon=True)
        thread.start()

    # ------------------------------------------------------------------
    # History management
    # ------------------------------------------------------------------
    def _load_history(self):
        db = lazy_import("nbchat.core.db")
        rows = db.load_history(self.session_id)
        self.history = rows
        self._render_history()

    def _render_history(self):
        """Rebuild the entire chat history display (used when switching sessions)."""
        children = []
        for role, content, tool_id, tool_name, tool_args in self.history:
            if role == "user":
                children.append(self._render_user_message(content))
            elif role == "analysis":
                children.append(self._render_analysis_message(content))
            elif role == "assistant":
                children.append(self._render_assistant_message(content, tool_id, tool_name, tool_args))
            elif role == "assistant_full":
                # Full assistant message (with reasoning and tool calls)
                try:
                    full_msg = json.loads(tool_args)
                    reasoning = full_msg.get("reasoning_content", "")
                    msg_content = full_msg.get("content", "")
                    tool_calls = full_msg.get("tool_calls", [])
                    html = styles.assistant_full_html(reasoning, msg_content, tool_calls)
                    children.append(widgets.HTML(value=html, layout=widgets.Layout(width="100%", margin="0")))
                except:
                    children.append(self._render_assistant_message(content, "", "", ""))
            elif role == "tool":
                children.append(self._render_tool_message(content, tool_id, tool_name, tool_args))
        self.chat_history.children = children

    def _render_user_message(self, content: str) -> widgets.HTML:
        return styles.create_user_widget(content)

    def _render_analysis_message(self, content: str) -> widgets.HTML:

        return styles.create_reasoning_widget(content)

    def _render_assistant_message(self, content: str, tool_id: str, tool_name: str, tool_args: str) -> widgets.HTML:

        if tool_id == "multiple":

            try:

                tool_calls = json.loads(tool_args)

                return styles.create_assistant_with_tools_widget(content, tool_calls)

            except:

                return styles.create_assistant_widget(content)

        elif tool_id:

            return styles.create_assistant_with_single_tool_widget(content, tool_name, tool_args)

        else:

            return styles.create_assistant_widget(content)

    def _render_tool_message(self, content: str, tool_id: str, tool_name: str, tool_args: str) -> widgets.HTML:
        return styles.create_tool_widget(content, tool_name)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def _on_new_chat(self, btn):
        self.session_id = str(uuid.uuid4())
        self.history = []
        db = lazy_import("nbchat.core.db")
        options = list(db.get_session_ids())
        if self.session_id not in options:
            options.append(self.session_id)
        self.session_dropdown.options = options
        self.session_dropdown.value = self.session_id
        self._render_history()

    def _on_session_change(self, change):
        if change["new"]:
            self.session_id = change["new"]
            self._load_history()

    def _on_send(self, *args):
        user_input = self.input_text.value.strip()
        if not user_input:
            return
        self.input_text.value = ""
        self.history.append(("user", user_input, "", "", ""))
        # Append user message directly to UI to avoid rebuild snap
        self.chat_history.children = list(self.chat_history.children) + [self._render_user_message(user_input)]
        db = lazy_import("nbchat.core.db")
        db.log_message(self.session_id, "user", user_input)
        self._process_conversation_turn()

    # ------------------------------------------------------------------
    # Core conversation processing (no rebuilds, only appends)
    # ------------------------------------------------------------------
    def _process_conversation_turn(self):
        client = lazy_import("nbchat.core.client")
        tools = lazy_import("nbchat.tools")

        messages = self._build_messages_for_api()
        messages = self._strip_reasoning_content(messages)  # New user turn

        tool_turn_count = 0

        while tool_turn_count <= self.MAX_TOOL_TURNS:
            reasoning, content, tool_calls, finish_reason = self._stream_assistant_response(
                client, tools, messages
            )

            # Store reasoning in history and database (UI already updated via placeholder)
            if reasoning:
                self.history.append(("analysis", reasoning, "", "", ""))
                db = lazy_import("nbchat.core.db")
                db.log_message(self.session_id, "analysis", reasoning)

            if not tool_calls or finish_reason != "tool_calls":
                # Final assistant message – store in history (UI already has placeholder with final content)
                if content:
                    self.history.append(("assistant", content, "", "", ""))
                    db = lazy_import("nbchat.core.db")
                    db.log_message(self.session_id, "assistant", content)
                break

            tool_turn_count += 1
            if tool_turn_count > self.MAX_TOOL_TURNS:
                warning = f"⚠️ Maximum tool call turns ({self.MAX_TOOL_TURNS}) reached. Stopping."
                # Show warning in UI
                warning_widget = self._render_assistant_message(warning, "", "", "")
                self.chat_history.children = list(self.chat_history.children) + [warning_widget]
                self.history.append(("assistant", warning, "", "", ""))
                db = lazy_import("nbchat.core.db")
                db.log_message(self.session_id, "assistant", warning)
                break

            # Full assistant message (with reasoning and tool calls)
            full_assistant_msg = {
                "role": "assistant",
                "content": content,
                "reasoning_content": reasoning,
                "tool_calls": tool_calls
            }
            messages.append(full_assistant_msg)
            self.history.append(("assistant_full", "", "full", "full", json.dumps(full_assistant_msg)))
            db.log_message(self.session_id, "assistant", content)  # log content separately

            # Execute tools and append results to UI directly
            for tc in tool_calls:
                tool_id = tc["id"]
                tool_name = tc["function"]["name"]
                tool_args_str = tc["function"]["arguments"]

                result = self._execute_tool(tool_name, tool_args_str)

                self.history.append(("tool", result, tool_id, tool_name, tool_args_str))
                db.log_tool_msg(self.session_id, tool_id, tool_name, tool_args_str, result)

                # Add tool result widget
                tool_widget = self._render_tool_message(result, tool_id, tool_name, tool_args_str)
                self.chat_history.children = list(self.chat_history.children) + [tool_widget]

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": result
                })

            # Do NOT call _render_history() here – UI updated incrementally

    def _build_messages_for_api(self) -> List[Dict[str, Any]]:
        messages = [{"role": "system", "content": self.system_prompt}]
        for role, content, tool_id, tool_name, tool_args in self.history:
            if role == "user":
                messages.append({"role": "user", "content": content})
            elif role == "assistant":
                if tool_id:
                    # Assistant row with a tool call (stored by log_tool_msg)
                    # Construct a proper assistant message with tool_calls
                    assistant_msg = {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": [
                            {
                                "id": tool_id,
                                "type": "function",
                                "function": {"name": tool_name, "arguments": tool_args}
                            }
                        ]
                    }
                    messages.append(assistant_msg)
                else:
                    messages.append({"role": "assistant", "content": content})
            elif role == "assistant_full":
                try:
                    full_msg = json.loads(tool_args)
                    messages.append(full_msg)
                except:
                    messages.append({"role": "assistant", "content": content})
            elif role == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": content
                })
        return messages

    def _strip_reasoning_content(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for msg in messages:
            if msg.get("role") == "assistant" and "reasoning_content" in msg:
                del msg["reasoning_content"]
        return messages

    def _stream_assistant_response(self, client, tools, messages):
        reasoning_placeholder = None
        assistant_placeholder = None
        reasoning_accum = ""
        content_accum = ""
        tool_calls_buffer = {}
        finish_reason = None

        stream = client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=True,
            tools=tools,
            max_tokens=4096
        )

        for chunk in stream:
            choice = chunk.choices[0]
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            delta = choice.delta

            # Reasoning
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                if reasoning_placeholder is None:
                    reasoning_placeholder = widgets.HTML(
                        value=styles.reasoning_placeholder_html(),
                        layout=widgets.Layout(width="100%", margin="0")
                    )
                    self.chat_history.children = list(self.chat_history.children) + [reasoning_placeholder]
                reasoning_accum += delta.reasoning_content
                reasoning_placeholder.value = styles.reasoning_html_with_content(reasoning_accum)

            # Assistant content
            if delta.content:
                if assistant_placeholder is None:
                    assistant_placeholder = widgets.HTML(
                        value=styles.assistant_placeholder_html(),
                        layout=widgets.Layout(width="100%", margin="0"))
                    # Insert after reasoning if it exists
                    children = list(self.chat_history.children)
                    if reasoning_placeholder is not None and reasoning_placeholder in children:
                        idx = children.index(reasoning_placeholder) + 1
                        children.insert(idx, assistant_placeholder)
                    else:
                        children.append(assistant_placeholder)
                    self.chat_history.children = children
                content_accum += delta.content
                assistant_placeholder.value = styles.assistant_html_with_content(content_accum)

            # Tool calls
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {
                            "id": tc_delta.id,
                            "type": "function",
                            "function": {
                                "name": tc_delta.function.name,
                                "arguments": ""
                            }
                        }
                    if tc_delta.function.arguments:
                        tool_calls_buffer[idx]["function"]["arguments"] += tc_delta.function.arguments

        tool_calls = [tool_calls_buffer[i] for i in sorted(tool_calls_buffer.keys())] if tool_calls_buffer else None
        return reasoning_accum, content_accum, tool_calls, finish_reason

    def _execute_tool(self, tool_name: str, args_json: str) -> str:
        from nbchat.tools import TOOLS
        try:
            args = json.loads(args_json)
            print(tool_name, args_json)
        except Exception as e:
            return f"❌ Failed to parse tool arguments: {e}"
        func = next((t.func for t in TOOLS if t.name == tool_name), None)
        if not func:
            return f"⚠️ Unknown tool '{tool_name}'"
        timeout = 60 if tool_name in ["browser", "run_tests"] else 30
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, **args)
            try:
                result = future.result(timeout=timeout)
                return str(result)
            except TimeoutError:
                return f"⏰ Tool '{tool_name}' timed out after {timeout} seconds."
            except Exception as e:
                return f"❌ Tool execution error: {e}"


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
