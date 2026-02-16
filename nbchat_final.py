"""
ipywidgets chat client with full feature parity to the Streamlit app.

This module provides an ipywidgets-based UI that replicates the functionality
of the Streamlit app (app.py), including:

* Persistent chat history using SQLite (chat_history.db)
* Real-time server status and metrics panel
* Sidebar with tools list, new chat, push to git, and ask code buttons
* Session selection (load existing conversations)
* Streaming responses with reasoning display
* Full tool call execution with multiple tool call support
* Proper rendering of tool calls with collapsible details
* Integration with the same chat logic as app.py (build_messages, stream_and_collect, process_tool_calls)

The UI is structured as a two-column layout:
  - Left sidebar: server status, tools list, buttons, session selector
  - Main area: chat history, input box, send button
"""

from __future__ import annotations

import asyncio
import ipywidgets as widgets
import json
import subprocess
import threading
import time
import uuid
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from IPython.display import display, clear_output

# Lazy imports for performance
_client = None
_tools = None
_chat_module = None
_db_module = None
_config_module = None
_push_module = None
_metrics_module = None
_repo_overview_module = None


def lazy_import(module_name: str, attribute: Optional[str] = None):
    """Import a module or attribute only when needed."""
    global _client, _tools, _chat_module, _db_module, _config_module, _push_module, _metrics_module, _repo_overview_module
    
    if module_name == "app.client":
        if _client is None:
            from app.client import get_client
            _client = get_client
        return _client()
    elif module_name == "app.tools":
        if _tools is None:
            from app.tools import get_tools
            _tools = get_tools
        return _tools()
    elif module_name == "app.chat":
        if _chat_module is None:
            import app.chat as chat_module
            _chat_module = chat_module
        return _chat_module
    elif module_name == "app.db":
        if _db_module is None:
            import app.db as db_module
            _db_module = db_module
        return _db_module
    elif module_name == "app.config":
        if _config_module is None:
            import app.config as config_module
            _config_module = config_module
        return _config_module
    elif module_name == "app.push_to_github":
        if _push_module is None:
            import app.push_to_github as push_module
            _push_module = push_module
        return _push_module
    elif module_name == "app.metrics_ui":
        if _metrics_module is None:
            import app.metrics_ui as metrics_module
            _metrics_module = metrics_module
        return _metrics_module
    elif module_name == "app.tools.repo_overview":
        if _repo_overview_module is None:
            from app.tools.repo_overview import func as repo_overview_func
            _repo_overview_module = repo_overview_func
        return _repo_overview_module
    else:
        raise ValueError(f"Unknown module {module_name}")


class ChatUI:
    """Main UI class for the ipywidgets chat interface."""
    
    def __init__(self):
        # Initialize database
        db = lazy_import("app.db")
        db.init_db()
        
        # Load config
        config = lazy_import("app.config")
        self.default_system_prompt = config.DEFAULT_SYSTEM_PROMPT
        self.model_name = config.MODEL_NAME
        
        # State
        self.session_id = str(uuid.uuid4())
        self.history: List[Tuple[str, str, str, str, str]] = []
        self.system_prompt = self.default_system_prompt
        self.repo_docs = ""
        self.has_pushed = False
        
        # Load existing session IDs
        self.session_ids = db.get_session_ids()
        
        # Widgets
        self._create_widgets()
        
        # Start metrics updater
        self._start_metrics_updater()
        
        # Load initial history
        self._load_history()
        
        # Display the UI
        self._display()
    
    def _create_widgets(self):
        """Create all ipywidgets components."""
        # === Sidebar widgets ===
        # Server status
        self.metrics_output = widgets.HTML(
            value="<i>Loading server status...</i>",
            layout=widgets.Layout(width="100%", border="1px solid gray", padding="10px")
        )
        
        # New chat button
        self.new_chat_btn = widgets.Button(
            description="New Chat",
            button_style="primary",
            layout=widgets.Layout(width="100%")
        )
        self.new_chat_btn.on_click(self._on_new_chat)
        
        # Push to Git button
        self.push_git_btn = widgets.Button(
            description="Push to Git",
            button_style="warning",
            layout=widgets.Layout(width="100%")
        )
        self.push_git_btn.on_click(self._on_push_git)
        
        # Ask Code button
        self.ask_code_btn = widgets.Button(
            description="Ask Code",
            button_style="info",
            layout=widgets.Layout(width="100%")
        )
        self.ask_code_btn.on_click(self._on_ask_code)
        
        # Session selector
        self.session_dropdown = widgets.Dropdown(
            options=self.session_ids,
            value=self.session_id if self.session_id in self.session_ids else "",
            description="Session:",
            disabled=False,
            layout=widgets.Layout(width="100%")
        )
        self.session_dropdown.observe(self._on_session_change, names="value")
        
        # Tools list
        self.tools_output = widgets.HTML(
            value="<b>Available Tools:</b><br>",
            layout=widgets.Layout(width="100%", border="1px solid lightgray", padding="10px")
        )
        self._update_tools_list()
        
        # === Main area widgets ===
        # Chat history display
        self.chat_history = widgets.VBox(
            [],
            layout=widgets.Layout(
                width="100%",
                height="400px",
                overflow_y="auto",
                border="1px solid #ccc",
                padding="10px"
            )
        )
        
        # Input area
        self.input_text = widgets.Text(
            placeholder="Enter request...",
            layout=widgets.Layout(width="80%")
        )
        self.send_btn = widgets.Button(
            description="Send",
            button_style="success",
            layout=widgets.Layout(width="18%", margin_left="2%")
        )
        self.input_box = widgets.HBox([self.input_text, self.send_btn])
        
        # Connect send action
        self.input_text.on_submit(self._on_send)
        self.send_btn.on_click(self._on_send)
        
        # === Layout ===
        # Sidebar column
        sidebar = widgets.VBox([
            widgets.HTML("<h3>Chat Controls</h3>"),
            self.metrics_output,
            widgets.HTML("<hr>"),
            self.new_chat_btn,
            self.push_git_btn,
            self.ask_code_btn,
            widgets.HTML("<hr>"),
            self.session_dropdown,
            widgets.HTML("<hr>"),
            self.tools_output,
        ], layout=widgets.Layout(width="25%", border="1px solid black", padding="10px"))
        
        # Main column
        main = widgets.VBox([
            widgets.HTML("<h2>Chat with GPT-OSS</h2>"),
            self.chat_history,
            self.input_box,
        ], layout=widgets.Layout(width="75%", padding="10px"))
        
        # Overall layout
        self.layout = widgets.HBox([sidebar, main])
    
    def _update_tools_list(self):
        """Update the tools list HTML."""
        tools = lazy_import("app.tools")
        tools_list = "<br>".join([tool["function"]["name"] for tool in tools])
        self.tools_output.value = f"<b>Available Tools:</b><br>{tools_list}"
    
    def _start_metrics_updater(self):
        """Start a background thread to update server metrics."""
        def update_loop():
            while True:
                try:
                    # Use the parse_log function directly
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
                        changed_files_list = self._changed_files()
                        content = f"<b>Server:</b> {emoji}<br><b>TPS:</b> <code>{tps}</code><br><i>{time.strftime('%H:%M:%S')}</i>"
                        if changed_files_list:
                            content += "<br><br><b>Changed files:</b><br>" + "<br>".join(changed_files_list)
                    else:
                        content = "<i>Log file not found</i>"
                except Exception as e:
                    content = f"<i>Error: {e}</i>"
                
                # Update widget in main thread
                self.metrics_output.value = content
                time.sleep(2)
        
        thread = threading.Thread(target=update_loop, daemon=True)
        thread.start()
    
    def _changed_files(self):
        """Get list of changed files (similar to metrics_ui.changed_files)."""
        try:
            diff = subprocess.check_output(["git", "diff", "--name-only", "HEAD"], text=True).splitlines()
            staged = subprocess.check_output(["git", "diff", "--name-only", "--cached"], text=True).splitlines()
            all_changes = set(diff + staged)
            out = []
            for f in all_changes:
                if "__pycache__" in f:
                    continue
                if f in {"app.py", "run.py", "requirements.txt"}:
                    out.append(f)
                elif (f.startswith("app/") or f.startswith("tests/")) and f.endswith(".py"):
                    out.append(f)
            return out
        except Exception:
            return []
    
    def _load_history(self):
        """Load chat history for current session."""
        db = lazy_import("app.db")
        rows = db.load_history(self.session_id)
        # Convert (role, content) tuples to 5-tuple format
        self.history = [(role, content, "", "", "") for role, content in rows]
        self._render_history()
    
    def _render_history(self):
        """Render the chat history into the chat_history widget."""
        children = []
        for role, content, tool_id, tool_name, tool_args in self.history:
            if role == "user":
                children.append(self._render_user_message(content))
            elif role == "assistant":
                children.append(self._render_assistant_message(content, tool_id, tool_name, tool_args))
            elif role == "analysis":
                children.append(self._render_analysis_message(content))
            elif role == "tool":
                children.append(self._render_tool_message(content, tool_id, tool_name, tool_args))
        
        self.chat_history.children = children
        # Scroll to bottom
        if children:
            self.chat_history.children[-1].scroll_to()
    
    def _render_user_message(self, content: str) -> widgets.HTML:
        """Create a widget for a user message."""
        return widgets.HTML(
            value=f'<div style="background-color: #e3f2fd; padding: 10px; border-radius: 10px; margin: 5px;"><b>User:</b> {content}</div>',
            layout=widgets.Layout(width="100%", margin="5px 0")
        )
    
    def _render_assistant_message(self, content: str, tool_id: str, tool_name: str, tool_args: str) -> widgets.HTML:
        """Create a widget for an assistant message."""
        if tool_id == "multiple":
            # Multiple tool calls - display as a special block
            try:
                tool_calls = json.loads(tool_args)
                tool_summary = ", ".join([tc.get("name", "unknown") for tc in tool_calls])
                details = "<br>".join([f"<b>{tc.get('name')}</b>: {tc.get('args', {})}" for tc in tool_calls])
                html = f'''
                <div style="background-color: #f1f8e9; padding: 10px; border-radius: 10px; margin: 5px;">
                    <b>Assistant:</b> {content}<br>
                    <details>
                        <summary>Tool calls: {tool_summary}</summary>
                        {details}
                    </details>
                </div>
                '''
            except:
                html = f'<div style="background-color: #f1f8e9; padding: 10px; border-radius: 10px; margin: 5px;"><b>Assistant:</b> {content}</div>'
        elif tool_id:
            # Single tool call
            html = f'''
            <div style="background-color: #f1f8e9; padding: 10px; border-radius: 10px; margin: 5px;">
                <b>Assistant:</b> {content}<br>
                <details>
                    <summary>Tool call: {tool_name}</summary>
                    Arguments: {tool_args}
                </details>
            </div>
            '''
        else:
            # Plain assistant message
            html = f'<div style="background-color: #f1f8e9; padding: 10px; border-radius: 10px; margin: 5px;"><b>Assistant:</b> {content}</div>'
        return widgets.HTML(value=html, layout=widgets.Layout(width="100%", margin="5px 0"))
    
    def _render_analysis_message(self, content: str) -> widgets.HTML:
        """Create a widget for analysis/reasoning message."""
        return widgets.HTML(
            value=f'''
            <div style="background-color: #fff3e0; padding: 10px; border-radius: 10px; margin: 5px;">
                <details open>
                    <summary><b>Reasoning</b></summary>
                    {content}
                </details>
            </div>
            ''',
            layout=widgets.Layout(width="100%", margin="5px 0")
        )
    
    def _render_tool_message(self, content: str, tool_id: str, tool_name: str, tool_args: str) -> widgets.HTML:
        """Create a widget for a tool result message."""
        preview = content[:50] + ("..." if len(content) > 50 else "")
        return widgets.HTML(
            value=f'''
            <div style="background-color: #fce4ec; padding: 10px; border-radius: 10px; margin: 5px;">
                <details>
                    <summary><b>Tool result ({tool_name})</b>: {preview}</summary>
                    <pre>{content}</pre>
                </details>
            </div>
            ''',
            layout=widgets.Layout(width="100%", margin="5px 0")
        )
    
    def _display(self):
        """Display the UI."""
        display(self.layout)
    
    def _on_new_chat(self, btn):
        """Handle new chat button click."""
        self.session_id = str(uuid.uuid4())
        self.history = []
        self.repo_docs = ""
        self.session_dropdown.options = lazy_import("app.db").get_session_ids()
        self._render_history()
    
    def _on_push_git(self, btn):
        """Handle push to git button click."""
        self.push_git_btn.disabled = True
        self.push_git_btn.description = "Pushing..."
        try:
            push_module = lazy_import("app.push_to_github")
            push_module.main()
            self.has_pushed = True
            # Show success message
            self._show_notification("✅ Pushed to git successfully!")
        except Exception as e:
            self._show_notification(f"❌ Push failed: {e}")
        finally:
            self.push_git_btn.disabled = False
            self.push_git_btn.description = "Push to Git"
    
    def _on_ask_code(self, btn):
        """Handle ask code button click."""
        self.ask_code_btn.disabled = True
        self.ask_code_btn.description = "Updating..."
        try:
            repo_overview_func = lazy_import("app.tools.repo_overview")
            result = repo_overview_func()
            self.system_prompt += "\n\n" + result
            self._show_notification("✅ Codebase docs updated!")
        except Exception as e:
            self._show_notification(f"❌ Failed to update codebase docs: {e}")
        finally:
            self.ask_code_btn.disabled = False
            self.ask_code_btn.description = "Ask Code"
    
    def _on_session_change(self, change):
        """Handle session dropdown change."""
        if change["new"]:
            self.session_id = change["new"]
            self._load_history()
    
    def _on_send(self, *args):
        """Handle sending a user message."""
        user_input = self.input_text.value.strip()
        if not user_input:
            return
        
        # Clear input
        self.input_text.value = ""
        
        # Add user message to history
        self.history.append(("user", user_input, "", "", ""))
        self._render_history()
        
        # Log to database
        db = lazy_import("app.db")
        db.log_message(self.session_id, "user", user_input)
        
        # Get client and tools
        client = lazy_import("app.client")
        tools = lazy_import("app.tools")
        
        # Build messages using the chat module
        chat = lazy_import("app.chat")
        messages = chat.build_messages(self.history, self.system_prompt, user_input)
        
        # Stream assistant response
        self._stream_assistant_response(client, tools, chat, messages)
    
    def _stream_assistant_response(self, client, tools, chat, messages):
        """Stream the assistant response and handle tool calls."""
        # Create placeholder for assistant message
        assistant_placeholder = widgets.HTML(
            value='<div style="background-color: #f1f8e9; padding: 10px; border-radius: 10px; margin: 5px;"><b>Assistant:</b> <i>Thinking...</i></div>',
            layout=widgets.Layout(width="100%", margin="5px 0")
        )
        reasoning_placeholder = None
        
        # Add assistant placeholder to UI
        self.chat_history.children = list(self.chat_history.children) + [assistant_placeholder]
        
        # Initialize accumulators
        reasoning_text = ""
        assistant_text = ""
        tool_calls_buffer = {}
        finished = False
        
        # Create the streaming request
        stream = client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=True,
            tools=tools,
        )
        
        # Process each chunk
        for chunk in stream:
            choice = chunk.choices[0]
            if choice.finish_reason == "stop":
                finished = True
                break
            delta = choice.delta
            
            # Reasoning content
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_text += delta.reasoning_content
                if reasoning_placeholder is None:
                    # Create reasoning placeholder and insert before assistant placeholder
                    reasoning_placeholder = widgets.HTML(
                        value='<div style="background-color: #fff3e0; padding: 10px; border-radius: 10px; margin: 5px;"><details open><summary><b>Reasoning</b></summary></div>',
                        layout=widgets.Layout(width="100%", margin="5px 0")
                    )
                    # Insert reasoning placeholder before assistant placeholder
                    children = list(self.chat_history.children)
                    idx = children.index(assistant_placeholder)
                    children.insert(idx, reasoning_placeholder)
                    self.chat_history.children = children
                # Update reasoning placeholder
                reasoning_placeholder.value = f'''
                <div style="background-color: #fff3e0; padding: 10px; border-radius: 10px; margin: 5px;">
                    <details open>
                        <summary><b>Reasoning</b></summary>
                        {reasoning_text}
                    </details>
                </div>
                '''
            
            # Assistant content
            if delta.content:
                assistant_text += delta.content
                assistant_placeholder.value = f'''
                <div style="background-color: #f1f8e9; padding: 10px; border-radius: 10px; margin: 5px;">
                    <b>Assistant:</b> {assistant_text}
                </div>
                '''
            
            # Tool calls
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
        
        # Final tool calls list
        tool_calls = list(tool_calls_buffer.values()) if tool_calls_buffer else None
        
        # Store reasoning and assistant messages in history and DB
        db = lazy_import("app.db")
        if reasoning_text:
            self.history.append(("analysis", reasoning_text, "", "", ""))
            db.log_message(self.session_id, "analysis", reasoning_text)
        if assistant_text:
            self.history.append(("assistant", assistant_text, "", "", ""))
            db.log_message(self.session_id, "assistant", assistant_text)
        
        # Handle tool calls if any
        if tool_calls and not finished:
            self.history = self._process_tool_calls(
                client, messages, self.session_id, self.history,
                tools, tool_calls, finished, assistant_text, reasoning_text
            )
            # Re-render history after tool calls
            self._render_history()
        else:
            # If no tool calls, we still need to update the placeholders with final content
            # (already done)
            pass
    def _process_tool_calls(self, client, messages, session_id, history, tools, tool_calls, finished, assistant_text, reasoning_text):
        """Execute tools and continue the conversation, handling multiple tool calls in one turn."""
        if not tool_calls:
            return history
        
        import json
        import concurrent.futures
        from app.tools import TOOLS
        
        # --- 1. Construct the assistant message that contains all tool calls ---
        tool_calls_list = []
        for tc in tool_calls:
            tool_calls_list.append({
                "id": tc.get("id"),
                "type": "function",
                "function": {
                    "name": tc.get("name"),
                    "arguments": tc.get("arguments") or "{}",
                },
            })
        
        assistant_msg = {
            "role": "assistant",
            "content": assistant_text,
            "reasoning_content": reasoning_text,
            "tool_calls": tool_calls_list,
        }
        messages.append(assistant_msg)
        
        # Store reasoning in history (as before)
        if reasoning_text:
            history.append(("analysis", reasoning_text, "", "", ""))
        
        # Store the combined assistant turn in history.
        tool_calls_data = json.dumps([
            {"id": tc.get("id"), "name": tc.get("name"), "args": tc.get("arguments")}
            for tc in tool_calls
        ])
        history.append(("assistant", assistant_text, "multiple", "tool_calls", tool_calls_data))
        
        # --- 2. Execute each tool and append tool responses ---
        for tc in tool_calls:
            tool_id = tc.get("id")
            tool_name = tc.get("name")
            tool_args = tc.get("arguments") or "{}"
            
            try:
                args = json.loads(tool_args)
            except Exception as exc:
                args = {}
                result = f"❌ JSON error: {exc}"
            else:
                func = next((t.func for t in TOOLS if t.name == tool_name), None)
                if func:
                    try:
                        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                        try:
                            timeout_sec = 60 if tool_name in ['browser', 'run_tests'] else 30
                            future = executor.submit(func, **args)
                            result = future.result(timeout=timeout_sec)
                        except concurrent.futures.TimeoutError:
                            result = f"⛔ Tool call {tool_name} timed out after {timeout_sec} seconds."
                        except Exception as exc:
                            result = f"❌ Tool error: {exc}"
                        finally:
                            executor.shutdown(wait=False)
                    except Exception as exc:
                        result = f"❌ Tool error: {exc}"
                else:
                    result = f"⚠️ Unknown tool '{tool_name}'"
            
            # Display tool result as a collapsible HTML widget
            preview = result[:50] + ("…" if len(result) > 50 else "")
            tool_html = f'''
            <div style="background-color: #fce4ec; padding: 10px; border-radius: 10px; margin: 5px;">
                <details>
                    <summary><b>Tool result ({tool_name})</b>: {preview}</summary>
                    <pre>{result}</pre>
                </details>
            </div>
            '''
            tool_widget = widgets.HTML(value=tool_html, layout=widgets.Layout(width="100%", margin="5px 0"))
            # Add to chat history
            self.chat_history.children = list(self.chat_history.children) + [tool_widget]
            
            # Append tool response to messages
            messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": result,
            })
            
            # Append to history
            history.append(("tool", result, tool_id, tool_name, tool_args))
            
            # Log to DB
            db = lazy_import("app.db")
            db.log_tool_msg(session_id, tool_id, tool_name, tool_args, result)
        
        # --- 3. Get the next assistant response (may be final answer or more tool calls) ---
        # We'll reuse _stream_assistant_response for the next turn, but we need to pass updated messages and history.
        # However, we can call stream_and_collect again, but we need to integrate with UI.
        # Simpler: we call _stream_assistant_response again with the updated messages and empty user input.
        # But we need to avoid infinite recursion. Instead, we'll manually stream the next assistant response.
        # Let's create a new streaming loop similar to the first part.
        
        # Create placeholder for next assistant turn
        next_assistant_placeholder = widgets.HTML(
            value='<div style="background-color: #f1f8e9; padding: 10px; border-radius: 10px; margin: 5px;"><b>Assistant:</b> <i>Processing tool results...</i></div>',
            layout=widgets.Layout(width="100%", margin="5px 0")
        )
        self.chat_history.children = list(self.chat_history.children) + [next_assistant_placeholder]
        
        reasoning_text2 = ""
        assistant_text2 = ""
        tool_calls_buffer2 = {}
        finished2 = False
        
        stream2 = client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=True,
            tools=tools,
        )
        
        for chunk in stream2:
            choice = chunk.choices[0]
            if choice.finish_reason == "stop":
                finished2 = True
                break
            delta = choice.delta
            
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_text2 += delta.reasoning_content
                # We could update a reasoning placeholder, but we didn't create one.
                # For simplicity, we'll just accumulate and display at the end.
            
            if delta.content:
                assistant_text2 += delta.content
                next_assistant_placeholder.value = f'''
                <div style="background-color: #f1f8e9; padding: 10px; border-radius: 10px; margin: 5px;">
                    <b>Assistant:</b> {assistant_text2}
                </div>
                '''
            
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_buffer2:
                        tool_calls_buffer2[idx] = {
                            "id": tc_delta.id,
                            "name": tc_delta.function.name,
                            "arguments": "",
                        }
                    if tc_delta.function.arguments:
                        tool_calls_buffer2[idx]["arguments"] += tc_delta.function.arguments
        
        tool_calls2 = list(tool_calls_buffer2.values()) if tool_calls_buffer2 else None
        
        # Store new reasoning and assistant messages
        db = lazy_import("app.db")
        if reasoning_text2:
            history.append(("analysis", reasoning_text2, "", "", ""))
            db.log_message(session_id, "analysis", reasoning_text2)
        if assistant_text2:
            history.append(("assistant", assistant_text2, "", "", ""))
            db.log_message(session_id, "assistant", assistant_text2)
        
        # If there are more tool calls, recursively process them
        if tool_calls2 and not finished2:
            history = self._process_tool_calls(
                client, messages, session_id, history, tools,
                tool_calls2, finished2, assistant_text2, reasoning_text2
            )
        
        return history
    
    def _show_notification(self, message: str, duration: int = 3):
        """Show a temporary notification."""
        notification = widgets.HTML(
            value=f'<div style="background-color: #333; color: white; padding: 10px; border-radius: 5px; position: fixed; top: 10px; right: 10px; z-index: 1000;">{message}</div>',
            layout=widgets.Layout(width="auto")
        )
        display(notification)
        time.sleep(duration)
        notification.close()


def run_chat() -> None:
    """Display the ipywidgets chat UI."""
    ui = ChatUI()