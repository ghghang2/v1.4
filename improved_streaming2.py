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
