from __future__ import annotations

import ipywidgets as widgets
import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import List, Tuple

from IPython.display import display

from nbchat.ui import chat_renderer as renderer
from nbchat.ui import tool_executor as executor
from nbchat.ui import chat_builder
from nbchat.compaction import CompactionEngine
from nbchat.ui.utils import changed_files
from nbchat.core.utils import lazy_import


class ChatUI:
    """Chat interface with streaming, reasoning, and safe tool execution."""

    MAX_TOOL_TURNS = 50

    def __init__(self):
        db = lazy_import("nbchat.core.db")
        db.init_db()

        config = lazy_import("nbchat.core.config")
        self.system_prompt = config.DEFAULT_SYSTEM_PROMPT
        self.model_name = config.MODEL_NAME
        self.compaction_engine = CompactionEngine(
            threshold=config.CONTEXT_TOKEN_THRESHOLD,
            tail_messages=config.TAIL_MESSAGES,
            summary_prompt=config.SUMMARY_PROMPT,
            summary_model=config.MODEL_NAME,
            system_prompt=self.system_prompt,
        )
        self.session_id = str(uuid.uuid4())
        # (role, content, tool_id, tool_name, tool_args)
        self.history: List[Tuple[str, str, str, str, str]] = []
        self._stop_streaming = False
        self._stream_thread = None
        # ------------------------------------------------------------------
        # Thread‑safety primitives
        # ------------------------------------------------------------------
        self._history_lock = threading.Lock()

        self._create_widgets()
        self._start_metrics_updater()
        self._load_history()
        display(self.layout)

    # ------------------------------------------------------------------
    # Widget creation
    # ------------------------------------------------------------------
    def _create_widgets(self):
        db = lazy_import("nbchat.core.db")

        self.metrics_output = widgets.HTML(
            value="<i>Loading server status...</i>",
            layout=widgets.Layout(width="100%", border="1px solid gray", padding="10px"),
        )
        self.tools_output = widgets.HTML(
            layout=widgets.Layout(width="100%", border="1px solid lightgray", padding="2px")
        )
        self._refresh_tools_list()

        new_chat_btn = widgets.Button(description="+", button_style="primary",
                                      layout=widgets.Layout(width="100%"))
        new_chat_btn.on_click(self._on_new_chat)

        options = list(db.get_session_ids())
        if self.session_id not in options:
            options.append(self.session_id)
        self.session_dropdown = widgets.Dropdown(options=options, value=self.session_id,
                                                  layout=widgets.Layout(width="100%"))
        self.session_dropdown.observe(self._on_session_change, names="value")

        sidebar = widgets.VBox([
            # widgets.HTML("<h3>Chat Controls</h3>"),
            self.metrics_output,
            widgets.HTML("<hr>"),
            new_chat_btn,
            widgets.HTML("<hr>"),
            self.tools_output,
            widgets.HTML("<hr>"),
            self.session_dropdown,
        ], layout=widgets.Layout(width="15%", border="1px solid lightgray"))

        self.chat_history = widgets.VBox([], layout=widgets.Layout(
            width="100%", height="100%", max_height="800px", overflow_y="auto",
            border="1px solid #ccc",
        ))
        self.input_text = widgets.Textarea(
            placeholder="...",
            layout=widgets.Layout(width="90%", min_height="50px", height="auto"),
            rows=2,
        )
        send_btn = widgets.Button(description="Send", button_style="success",
                                   layout=widgets.Layout(width="5%", padding="0", margin="0"))
        stop_btn = widgets.Button(description="Stop", button_style="warning",
                                   layout=widgets.Layout(width="5%", padding="0", margin="0"))
        send_btn.on_click(self._on_send)
        stop_btn.on_click(lambda *_: setattr(self, "_stop_streaming", True))

        main = widgets.VBox([
            widgets.HTML(""),
            self.chat_history,
            widgets.HBox([self.input_text, send_btn, stop_btn]),
        ], layout=widgets.Layout(width="100%", padding="0px"))

        self.layout = widgets.HBox([sidebar, main])

    def _refresh_tools_list(self):
        tools = lazy_import("nbchat.tools")
        names = "<br>".join(t["function"]["name"] for t in tools)
        self.tools_output.value = f"<b>Tools</b><br>{names}"

    # ------------------------------------------------------------------
    # Metrics updater
    # ------------------------------------------------------------------
    def _start_metrics_updater(self):
        def update_loop():
            from nbchat.ui.styles import CODE_COLOR
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
                        content = (
                            f'<b>Server</b> {emoji}<br>'
                            f'<b>TPS:</b> <code style="color:{CODE_COLOR};">{tps}</code><br>'
                            f'<i>{time.strftime("%H:%M:%S")}</i>'
                        )
                        try:
                            cf = changed_files()
                            if cf:
                                content += "<br><br><b>Changed files:</b><br>" + "<br>".join(cf)
                        except Exception:
                            pass
                    else:
                        content = "<i>Log file not found</i>"
                except Exception as e:
                    content = f"<i>Error: {e}</i>"
                self.metrics_output.value = content
                time.sleep(1)

        threading.Thread(target=update_loop, daemon=True).start()

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    def _load_history(self):
        db = lazy_import("nbchat.core.db")
        self.history = db.load_history(self.session_id)
        self._render_history()

    def _render_history(self):
        children = []
        for role, content, tool_id, tool_name, tool_args in self.history:
            if role == "user":
                children.append(renderer.render_user(content))
            elif role == "analysis":
                children.append(renderer.render_reasoning(content))
            elif role == "assistant":
                children.append(self._widget_for_assistant(content, tool_id, tool_args))
            elif role == "assistant_full":
                try:
                    msg = json.loads(tool_args)
                    children.append(renderer.render_assistant_full(
                        msg.get("reasoning_content", ""),
                        msg.get("content", ""),
                        msg.get("tool_calls", []),
                    ))
                except Exception:
                    children.append(renderer.render_assistant(content))
            elif role == "tool":
                children.append(renderer.render_tool(content, tool_name, tool_args))
            elif role == "system":
                children.append(renderer.render_system(content))
            elif role == "compacted":
                children.append(renderer.render_compacted_summary(content))
        self.chat_history.children = children

    def _maybe_compact(self, messages=None):
        """Fire off async compaction if threshold exceeded. Does not block."""
        if not self.history:
            return False
        if self.compaction_engine.should_compact(self.history):
            # Cancel any previous pending compaction before submitting a new one
            if self.compaction_engine._pending and not self.compaction_engine._pending.done():
                self.compaction_engine._pending.cancel()
            # Take a snapshot of history for the background thread
            history_snapshot = list(self.history)
            self.compaction_engine._pending = self.compaction_engine._executor.submit(
                self.compaction_engine.compact_history, history_snapshot
            )
            return True
        return False

    def _drain_compaction(self, messages):
        """Apply any pending compaction result. Only updates data, never re-renders."""
        future = self.compaction_engine._pending
        if future is None:
            return
        if not future.done():
            return  # don't block — will drain on next turn
        try:
            new_history = future.result()
            self.compaction_engine._pending = None
            db = lazy_import("nbchat.core.db")
            self.history = new_history
            db.replace_session_history(self.session_id, new_history)
            messages.clear()
            messages.extend(chat_builder.build_messages(self.history, self.system_prompt))
            # Append just the compaction notice widget, no full re-render
            for role, content, _, _, _ in self.history:
                if role == "compacted":
                    self._append(renderer.render_compacted_summary(content))
                    break
        except Exception as e:
            import sys
            print(f"Compaction failed: {e}", file=sys.stderr)
            self.compaction_engine._pending = None

    def _widget_for_assistant(self, content: str, tool_id: str, tool_args: str) -> widgets.HTML:
        if tool_id == "multiple":
            try:
                return renderer.render_assistant_with_tools(content, json.loads(tool_args))
            except Exception:
                pass
        return renderer.render_assistant(content)

    def _append(self, widget: widgets.HTML):
        self.chat_history.children = list(self.chat_history.children) + [widget]

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def _on_new_chat(self, _):
        db = lazy_import("nbchat.core.db")
        self.session_id = str(uuid.uuid4())
        self.history = []
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

    def _on_send(self, _):
        user_input = self.input_text.value.strip()
        if not user_input:
            return

        db = lazy_import("nbchat.core.db")
        with self._history_lock:
            # Stop existing stream if running
            if self._stream_thread and self._stream_thread.is_alive():
                self._stop_streaming = True
                self._stream_thread.join()

            # Cancel any pending compaction from the previous turn
            if self.compaction_engine._pending and not self.compaction_engine._pending.done():
                self.compaction_engine._pending.cancel()
            self.compaction_engine._pending = None

            # Append the new user message
            self.history.append(("user", user_input, "", "", ""))
            self._append(renderer.render_user(user_input))
            db.log_message(self.session_id, "user", user_input)

            self.input_text.value = ""
            self._stop_streaming = False
            self._stream_thread = threading.Thread(
                target=self._process_conversation_turn,
                daemon=True,
            )
            self._stream_thread.start()

    # ------------------------------------------------------------------
    # Conversation loop
    # ------------------------------------------------------------------
    def _process_conversation_turn(self):
        client = lazy_import("nbchat.core.client")
        tools  = lazy_import("nbchat.tools")
        db     = lazy_import("nbchat.core.db")
        messages = chat_builder.build_messages(self.history, self.system_prompt)
        for msg in messages:
            msg.pop("reasoning_content", None)

        for turn in range(self.MAX_TOOL_TURNS + 1):
            if self._stop_streaming:
                break

            self._drain_compaction(messages)

            reasoning, content, tool_calls, finish_reason = self._stream_response(client, tools, messages)

            if reasoning:
                self.history.append(("analysis", reasoning, "", "", ""))
                self._maybe_compact(messages)
                db.log_message(self.session_id, "analysis", reasoning)

            if not tool_calls or finish_reason != "tool_calls":
                if content:
                    self.history.append(("assistant", content, "", "", ""))
                    self._maybe_compact(messages)
                    db.log_message(self.session_id, "assistant", content)
                break

            if turn == self.MAX_TOOL_TURNS:
                warning = f"⚠️ Maximum tool turns ({self.MAX_TOOL_TURNS}) reached."
                self._append(renderer.render_assistant(warning))
                self.history.append(("assistant", warning, "", "", ""))
                db.log_message(self.session_id, "assistant", warning)
                break

            full_msg = {"role": "assistant", "content": content,
                        "reasoning_content": reasoning, "tool_calls": tool_calls}
            messages.append(full_msg)
            self.history.append(("assistant_full", "", "full", "full", json.dumps(full_msg)))
            self._maybe_compact(messages)
            db.log_message(self.session_id, "assistant", content)

            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                tool_args = tc["function"]["arguments"]
                result = executor.run_tool(tool_name, tool_args)
                self.history.append(("tool", result, tc["id"], tool_name, tool_args))
                db.log_tool_msg(self.session_id, tc["id"], tool_name, tool_args, result)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                compacted = self._maybe_compact(messages)
                if not compacted:
                    self._append(renderer.render_tool(result, tool_name, tool_args))

    def _stream_response(self, client, tools, messages):
        reasoning_widget = None
        assistant_widget = None
        reasoning_accum = ""
        content_accum = ""
        tool_buffer: dict = {}
        finish_reason = None

        stream = client.chat.completions.create(
            model=self.model_name, messages=messages,
            stream=True, tools=tools, max_tokens=4096,
        )
        for chunk in stream:
            if self._stop_streaming:
                stream.close()
                break
            choice = chunk.choices[0]
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            delta = choice.delta

            if getattr(delta, "reasoning_content", None):
                if reasoning_widget is None:
                    reasoning_widget = renderer.render_placeholder("reasoning")
                    self._append(reasoning_widget)
                reasoning_accum += delta.reasoning_content
                reasoning_widget.value = renderer.render_reasoning(reasoning_accum).value

            if delta.content:
                if assistant_widget is None:
                    assistant_widget = renderer.render_placeholder("assistant")
                    children = list(self.chat_history.children)
                    if reasoning_widget in children:
                        children.insert(children.index(reasoning_widget) + 1, assistant_widget)
                    else:
                        children.append(assistant_widget)
                    self.chat_history.children = children
                content_accum += delta.content
                assistant_widget.value = renderer.render_assistant(content_accum).value

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    entry = tool_buffer.setdefault(tc.index, {
                        "id": tc.id, "type": "function",
                        "function": {"name": tc.function.name, "arguments": ""},
                    })
                    if tc.function.arguments:
                        entry["function"]["arguments"] += tc.function.arguments

        tool_calls = [tool_buffer[i] for i in sorted(tool_buffer)] if tool_buffer else None
        return reasoning_accum, content_accum, tool_calls, finish_reason