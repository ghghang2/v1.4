"""ChatUI — main entry point.

Composes ContextMixin and ConversationMixin into a single widget-based
chat interface.  This file contains only widget creation, history
rendering, and event handling.  Context management lives in
context_manager.py and the conversation loop in conversation.py.
"""
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
from nbchat.ui import chat_builder
from nbchat.ui.context_manager import ContextMixin
from nbchat.ui.conversation import ConversationMixin
from nbchat.ui.utils import changed_files
from nbchat.core.utils import lazy_import


class ChatUI(ContextMixin, ConversationMixin):
    """Chat interface with streaming, reasoning, and tool execution."""

    MAX_TOOL_TURNS = 100
    # Number of user turns to include in the model's context window.
    WINDOW_TURNS = 8

    def __init__(self):
        db = lazy_import("nbchat.core.db")
        db.init_db()

        config = lazy_import("nbchat.core.config")
        self.system_prompt = config.DEFAULT_SYSTEM_PROMPT
        self.model_name = config.MODEL_NAME

        self.session_id = str(uuid.uuid4())
        # Full append-only history — persisted to DB and shown in UI.
        # (role, content, tool_id, tool_name, tool_args)
        self.history: List[Tuple[str, str, str, str, str]] = []
        # Running one-line log of tool actions — injected into system prompt
        # so the model never loses track of what it has done.
        self.task_log: List[str] = []

        self._stop_streaming = False
        self._stream_thread = None

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

        new_chat_btn = widgets.Button(
            description="+", button_style="primary",
            layout=widgets.Layout(width="100%"),
        )
        new_chat_btn.on_click(self._on_new_chat)

        options = list(db.get_session_ids())
        if self.session_id not in options:
            options.append(self.session_id)
        self.session_dropdown = widgets.Dropdown(
            options=options, value=self.session_id,
            layout=widgets.Layout(width="100%"),
        )
        self.session_dropdown.observe(self._on_session_change, names="value")

        sidebar = widgets.VBox([
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
        send_btn = widgets.Button(
            description="Send", button_style="success",
            layout=widgets.Layout(width="5%", padding="0", margin="0"),
        )
        stop_btn = widgets.Button(
            description="Stop", button_style="warning",
            layout=widgets.Layout(width="5%", padding="0", margin="0"),
        )
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
                                m = re.search(
                                    r"(?P<value>\d+(?:\.\d+)?)\s+tokens per second",
                                    line, re.IGNORECASE,
                                )
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
        self.task_log = db.load_task_log(self.session_id)
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
        self.chat_history.children = children

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
        self.task_log = []
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

        if self._stream_thread and self._stream_thread.is_alive():
            self._stop_streaming = True
            self._stream_thread.join()

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