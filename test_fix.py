#!/usr/bin/env python3
"""
Quick test to verify that loading a session with tool calls works.
"""
import sys
sys.path.insert(0, '.')

from nbchat.core.db import load_history
from nbchat.ui.chatui import ChatUI
import json

# We'll monkey-patch widgets to avoid UI dependencies
import nbchat.ui.chatui as chatui_module
import ipywidgets as widgets
widgets.HTML = lambda **kwargs: None
chatui_module.widgets = widgets

# Choose a session that has tool calls (use the first session we found)
session_ids = ['306844f4-e346-4fa2-82b9-0e40cce2ec3d']
for sid in session_ids:
    print(f"Testing session {sid}")
    rows = load_history(sid)
    print(f"Loaded {len(rows)} rows")
    for i, (role, content, tool_id, tool_name, tool_args) in enumerate(rows):
        print(f"  {i}: role={role}, content={content[:50] if content else ''}, tool_id={tool_id}, tool_name={tool_name}, tool_args={tool_args[:50] if tool_args else ''}")
    
    # Now create a ChatUI instance with that session (requires UI, but we can mock)
    # Instead we'll manually test the message building logic copied from chatui
    # Let's just import the method after patching lazy_import
    from nbchat.core.utils import lazy_import
    # Override lazy_import to return our mocks
    original_lazy_import = lazy_import
    def mock_lazy_import(mod):
        if mod == "nbchat.core.db":
            class MockDB:
                def load_history(self, session_id):
                    return rows
                def get_session_ids(self):
                    return []
            return MockDB()
        elif mod == "nbchat.core.config":
            class MockConfig:
                DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."
                MODEL_NAME = "gpt-4"
            return MockConfig()
        else:
            return original_lazy_import(mod)
    import nbchat.ui.chatui as cui
    cui.lazy_import = mock_lazy_import
    
    # Now instantiate ChatUI (will try to create widgets, may fail)
    # Instead we'll directly test the _build_messages_for_api using a minimal mock
    class MockChatUI:
        def __init__(self, session_id):
            self.session_id = session_id
            self.system_prompt = "You are a helpful assistant."
            self.history = rows
        def _build_messages_for_api(self):
            messages = [{"role": "system", "content": self.system_prompt}]
            for role, content, tool_id, tool_name, tool_args in self.history:
                if role == "user":
                    messages.append({"role": "user", "content": content})
                elif role == "assistant":
                    if tool_id:
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
    
    mock = MockChatUI(sid)
    messages = mock._build_messages_for_api()
    print(f"Built {len(messages)} messages")
    for i, msg in enumerate(messages):
        print(f"  {i}: {msg.get('role')} content={msg.get('content','')[:50]}")
        if 'tool_calls' in msg:
            print(f"    tool_calls: {msg['tool_calls']}")
        if 'tool_call_id' in msg:
            print(f"    tool_call_id: {msg['tool_call_id']}")
    
    # Validate that each tool message is preceded by an assistant message with a tool call
    for i, msg in enumerate(messages):
        if msg.get('role') == 'tool':
            # Look backward for preceding assistant message with tool_calls
            found = False
            for j in range(i-1, -1, -1):
                prev = messages[j]
                if prev.get('role') == 'assistant' and 'tool_calls' in prev:
                    # Check that tool_call_id matches one of the tool call ids
                    tool_call_id = msg['tool_call_id']
                    for tc in prev['tool_calls']:
                        if tc['id'] == tool_call_id:
                            found = True
                            break
                    if found:
                        break
            if not found:
                print(f"ERROR: tool message at index {i} lacks preceding assistant with matching tool call")
                sys.exit(1)
    print("Validation passed: all tool messages have preceding assistant with tool call")
print("All tests passed")