"""
Centralized styling for nbchat UI components.

This module provides a single place to define colors, spacing, border radii,
and other style properties used across the chat interface.

To customize the appearance of the chat interface, modify the constants
defined in the "Color palette" and "Spacing and layout" sections below.

Examples:
    - Change user message background color: modify BACKGROUND_USER
    - Change assistant message border radius: modify BORDER_RADIUS
    - Adjust padding around messages: modify PADDING
    - Change reasoning message border radius (special case): modify REASONING_BORDER_RADIUS

All style changes will automatically propagate to:
    - User messages
    - Assistant messages (including those with tool calls)
    - Reasoning messages
    - Tool result messages
    - Assistant full messages (with reasoning and tool calls)
    - Streaming placeholders

Note: Functional styles (e.g., white-space: pre-wrap for tool results) are
kept inline as they are not purely aesthetic.
"""

from typing import Dict, Any, List, Optional
import json
from nbchat.ui.utils import md_to_html
import re
# -----------------------------------------------------------------------------
# Color palette
# -----------------------------------------------------------------------------

# Background colors for different message types
BACKGROUND_SYSTEM = "#f5f5f5"        # light gray (optional)
BACKGROUND_USER = BACKGROUND_SYSTEM          
BACKGROUND_ASSISTANT = "#F0FFF0"   
BACKGROUND_REASONING = BACKGROUND_SYSTEM
BACKGROUND_TOOL = BACKGROUND_SYSTEM


# Border colors (currently not used but available for future)
BORDER_USER = BACKGROUND_SYSTEM
BORDER_ASSISTANT = BACKGROUND_SYSTEM
BORDER_REASONING = BACKGROUND_SYSTEM
BORDER_TOOL = BACKGROUND_SYSTEM

# Border radius variations
ASSISTANT_FULL_BORDER_RADIUS = "0px"

# Text colors (currently default black)
TEXT_COLOR = "inherit"

# -----------------------------------------------------------------------------
# Spacing and layout
# -----------------------------------------------------------------------------

PADDING = "0px"
BORDER_RADIUS = "0px"
MARGIN = "0"
MARGIN_BETWEEN_MESSAGES = "0"

# Special cases
REASONING_BORDER_RADIUS = "0px"  # reasoning uses 0px in current code

# -----------------------------------------------------------------------------
# Style dictionary generators
# -----------------------------------------------------------------------------

def user_style_dict() -> Dict[str, str]:
    """Return CSS style dict for user message container."""
    return {
        "background-color": BACKGROUND_USER,
        "padding": PADDING,
        "border-radius": BORDER_RADIUS,
        "margin": MARGIN,
    }

def assistant_style_dict() -> Dict[str, str]:
    """Return CSS style dict for assistant message container."""
    return {
        "background-color": BACKGROUND_ASSISTANT,
        "padding": PADDING,
        "border-radius": BORDER_RADIUS,
        "margin": MARGIN,
    }

def reasoning_style_dict() -> Dict[str, str]:
    """Return CSS style dict for reasoning container."""
    return {
        "background-color": BACKGROUND_REASONING,
        "padding": PADDING,
        "border-radius": REASONING_BORDER_RADIUS,
        "margin": MARGIN,
    }

def assistant_full_style_dict() -> Dict[str, str]:
    """Return CSS style dict for assistant_full message container."""
    return {
        "background-color": BACKGROUND_ASSISTANT,
        "padding": PADDING,
        "border-radius": ASSISTANT_FULL_BORDER_RADIUS,
        "margin": MARGIN,
    }

def tool_style_dict() -> Dict[str, str]:
    """Return CSS style dict for tool result container."""
    return {
        "background-color": BACKGROUND_TOOL,
        "padding": PADDING,
        "border-radius": BORDER_RADIUS,
        "margin": MARGIN,
    }

def system_style_dict() -> Dict[str, str]:
    """Return CSS style dict for system messages."""
    return {
        "background-color": BACKGROUND_SYSTEM,
        "padding": PADDING,
        "border-radius": BORDER_RADIUS,
        "margin": MARGIN,
    }

# -----------------------------------------------------------------------------
# HTML generation helpers
# -----------------------------------------------------------------------------

def style_dict_to_css(style_dict: Dict[str, str]) -> str:
    """Convert a style dictionary to a CSS style string."""
    return "; ".join(f"{k}: {v}" for k, v in style_dict.items())

def wrap_in_div(content: str, style_dict: Dict[str, str], **kwargs) -> str:
    """Wrap content in a div with the given style.
    
    Additional keyword arguments are added as attributes to the div.
    Example: wrap_in_div("hello", user_style_dict(), class_="message")
    """
    style = style_dict_to_css(style_dict)
    attrs = []
    for key, value in kwargs.items():
        # Convert Python keyword args to HTML attributes
        attr_name = key.rstrip("_").replace("_", "-")
        attrs.append(f'{attr_name}="{value}"')
    attrs_str = " " + " ".join(attrs) if attrs else ""
    return f'<div style="{style}"{attrs_str}>{content}</div>'

def user_message_html(content: str, prefix: str = "<b>User:</b> ") -> str:
    """Generate HTML for a user message."""
    
    raw_html = md_to_html(content)
    # Remove paragraph margins
    
    # Convert paragraphs to inline spans to keep title and content on the same line
    styled_content = re.sub(r'<p([^>]*)>', r'<span\1 style="margin:0;">', raw_html)
    styled_content = re.sub(r'</p>', r'</span>', styled_content)
    styled_content = f"{prefix}{styled_content}"
    return wrap_in_div(styled_content, user_style_dict())

def assistant_message_html(content: str, prefix: str = "<b>Assistant:</b> ") -> str:
    """Generate HTML for an assistant message."""
    
    raw_html = md_to_html(content)
    
    styled_content = re.sub(r'<p([^>]*)>', r'<span\1 style="margin:0;">', raw_html)
    styled_content = re.sub(r'</p>', r'</span>', styled_content)
    styled_content = f"{prefix}{styled_content}"
    return wrap_in_div(styled_content, assistant_style_dict())

def reasoning_html(content: str, summary: str = "<b>Reasoning</b>", open: bool = False) -> str:
    """Generate HTML for a reasoning message.
    The reasoning title and the content are placed on the same line by
    embedding the content directly after the ``<summary>`` tag.  This
    allows the text to stream inline next to the title instead of
    starting on a new line.
    """
    
    raw_html = md_to_html(content)
    
    raw_html = re.sub(r'<p([^>]*)>', r'<p\1 style="margin:0;">', raw_html)
    details_open = "open" if open else ""
    # Place the content immediately after the summary tag.
    # Use flex layout to keep header and content on the same line.
    # The original implementation placed the rendered content inside the
    # ``<summary>`` element and used ``display:flex`` which caused the
    # summary and its content to appear side‑by‑side.  ``<summary>`` is
    # meant to be a *heading* for the details, not a container for the
    # full content.  We now place the content *after* the ``</summary>``
    # tag so it expands on a new line.  The flex styles are removed to
    # avoid horizontal layout.
    inner = f"<details {details_open} style=\"margin:0; padding:0;\"><summary style=\"margin:0;\">{summary}</summary>{raw_html}</details>"
    return wrap_in_div(inner, reasoning_style_dict())

def reasoning_placeholder_html() -> str:
    """Generate HTML for an empty reasoning placeholder (collapsed).
    The details element is styled with zero margin/padding for consistency.
    """
    style = style_dict_to_css(reasoning_style_dict())
    return f'<div style="{style}"><details style="margin:0; padding:0;"><summary style="margin:0;"><b>Reasoning</b></summary></details></div>'

def reasoning_html_with_content(content: str, open: bool = False) -> str:
    """Generate HTML for reasoning with content (for streaming updates).
    The content is streamed inline next to the title.
    """
    
    raw_html = md_to_html(content)
    
    raw_html = re.sub(r'<p([^>]*)>', r'<p\1 style="margin:0;">', raw_html)
    details_open = "open" if open else ""
    # Same reasoning as in ``reasoning_html`` – the content should be
    # outside the summary element.
    inner = f'''<details {details_open} style=\"margin:0; padding:0;\"><summary style=\"margin:0;\"><b>Reasoning</b></summary>{raw_html}</details>'''
    return wrap_in_div(inner, reasoning_style_dict())

def assistant_placeholder_html() -> str:
    """Generate HTML for an empty assistant placeholder."""
    # Note: empty content, just the prefix
    style = style_dict_to_css(assistant_style_dict())
    return f'<div style="{style}"><b>Assistant:</b> </div>'

def assistant_html_with_content(content: str) -> str:
    """Generate HTML for assistant message with content (for streaming updates)."""
    
    raw_html = md_to_html(content)
    
    raw_html = re.sub(r'<p([^>]*)>', r'<p\1 style="margin:0;">', raw_html)
    inner = f'''<b>Assistant:</b> {raw_html}'''
    # Use wrap_in_div to ensure consistent styling
    style = style_dict_to_css(assistant_style_dict())
    return f'<div style="{style}">{inner}</div>'

def assistant_full_html(reasoning: str, content: str, tool_calls: List[Dict[str, Any]]) -> str:
    """Generate HTML for an assistant_full message with reasoning and tool calls."""
    
    html_parts = []
    if reasoning:
        raw = md_to_html(reasoning)
        
        raw = re.sub(r'<p([^>]*)>', r'<p\1 style="margin:0;">', raw)
        html_parts.append(f'<details style=\"margin:0; padding:0;\"><summary style=\"margin:0;\"><b>Reasoning</b></summary>{raw}</details>')
    if tool_calls:
        tool_summary = ", ".join([tc.get("function", {}).get("name", "unknown") for tc in tool_calls])
        html_parts.append(f'<details style=\"margin:0; padding:0;\"><summary style=\"margin:0;\">Tool calls: {tool_summary}</summary>')
        for tc in tool_calls:
            name = tc.get("function", {}).get("name", "unknown")
            args = tc.get("function", {}).get("arguments", "{}")
            html_parts.append(f'<b>{name}</b>: <code>{args}</code><br>')
        html_parts.append('</details>')
    raw = md_to_html(content)
    
    raw = re.sub(r'<p([^>]*)>', r'<p\1 style="margin:0;">', raw)
    html_parts.append(f'<b>Assistant:</b> {raw}')
    inner = "".join(html_parts)
    # Note: using assistant_full_style_dict which has border-radius 8px
    style = style_dict_to_css(assistant_full_style_dict())
    return f'<div style="{style}">{inner}</div>'

def tool_result_html(
    content: str,
    tool_name: str = "",
    preview: str = "",
    tool_args: str = "",
):
    """Generate HTML for a tool result message.

    Parameters
    ----------
    content:
        Full tool output.
    tool_name:
        Name of the tool that produced the result.
    preview:
        Short excerpt shown in the collapsed summary.  If omitted, the first 50
        characters of ``content`` are used.
    tool_args:
        Arguments that were passed to the tool.  These are displayed in the
        summary to provide context.
    """
    if not preview:
        preview = content[:50] + ("..." if len(content) > 50 else "")
    if tool_name:
        summary = f"<b>Tool result ({tool_name})</b>: {preview}"
    else:
        summary = f"<b>Tool result:</b> {preview}"
    if tool_args:
        # Escape for HTML
        escaped_args = tool_args.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        summary += f" | <b>Args:</b> {escaped_args}"
    inner = f"""<details style=\"margin:0; padding:0;\">
        <summary>{summary}</summary>
        <pre style=\"white-space: pre-wrap; word-wrap: break-word;\">{content}</pre>
    </details>"""
    return wrap_in_div(inner, tool_style_dict())

# -----------------------------------------------------------------------------
# Assistant message with tool calls
# -----------------------------------------------------------------------------

def assistant_message_with_tools_html(
    content: str,
    tool_calls: List[Dict[str, Any]],
    prefix: str = "<b>Assistant:</b> "
) -> str:
    """Generate HTML for an assistant message that includes tool calls.
    
    Args:
        content: The assistant's text content.
        tool_calls: A list of tool call dicts, each with keys:
            - "function": dict with "name" and "arguments"
            - "id": optional tool call id
        prefix: HTML prefix for the assistant label.
    """
    
    raw_html = md_to_html(content)
    
    raw_html = re.sub(r'<p([^>]*)>', r'<p\1 style="margin:0;">', raw_html)
    styled_content = f"{prefix}{raw_html}"
    
    if not tool_calls:
        return wrap_in_div(styled_content, assistant_style_dict())
    
    tool_summary = ", ".join(tc.get("function", {}).get("name", "unknown") for tc in tool_calls)
    details_lines = []
    for tc in tool_calls:
        name = tc.get("function", {}).get("name", "unknown")
        args = tc.get("function", {}).get("arguments", "{}")
        details_lines.append(f"<b>{name}</b>: <code>{args}</code>")
    details_html = "<br>".join(details_lines)
    
    inner = f"""{styled_content}<br>
<details style=\"margin:0; padding:0;\"><summary style=\"margin:0;\">Tool calls: {tool_summary}</summary>
    {details_html}
</details>"""
    return wrap_in_div(inner, assistant_style_dict())

def assistant_message_with_single_tool_html(
    content: str,
    tool_name: str,
    tool_args: str,
    prefix: str = "<b>Assistant:</b> "
) -> str:
    """Generate HTML for an assistant message with a single tool call."""
    
    raw_html = md_to_html(content)
    
    raw_html = re.sub(r'<p([^>]*)>', r'<p\1 style="margin:0;">', raw_html)
    styled_content = f"{prefix}{raw_html}"
    inner = f"""{styled_content}<br>
<details style=\"margin:0; padding:0;\"><summary style=\"margin:0;\">Tool call: {tool_name}</summary>
    Arguments: <code>{tool_args}</code>
</details>"""
    return wrap_in_div(inner, assistant_style_dict())

# -----------------------------------------------------------------------------
# Widget creation helpers (optional)
# -----------------------------------------------------------------------------

def create_html_widget(html: str, width: str = "100%", margin: str = "0") -> "widgets.HTML":
    """Create an ipywidgets.HTML widget with consistent layout."""
    import ipywidgets as widgets
    return widgets.HTML(
        value=html,
        layout=widgets.Layout(width=width, margin=margin)
    )

def create_user_widget(content: str) -> "widgets.HTML":
    """Create a user message widget."""
    return create_html_widget(user_message_html(content))

def create_assistant_widget(content: str) -> "widgets.HTML":
    """Create an assistant message widget."""
    return create_html_widget(assistant_message_html(content))

def create_reasoning_widget(content: str, open: bool = True) -> "widgets.HTML":
    """Create a reasoning message widget."""
    return create_html_widget(reasoning_html(content, open=open))

def create_tool_widget(content: str, tool_name: str = "", tool_args: str = "") -> "widgets.HTML":
    """Create a tool result widget."""
    return create_html_widget(tool_result_html(content, tool_name=tool_name, tool_args=tool_args))

def create_assistant_with_tools_widget(
    content: str,
    tool_calls: List[Dict[str, Any]]
) -> "widgets.HTML":
    """Create an assistant message widget that includes tool calls."""
    return create_html_widget(
        assistant_message_with_tools_html(content, tool_calls),
        margin="0"
    )

def create_assistant_with_single_tool_widget(
    content: str,
    tool_name: str,
    tool_args: str
) -> "widgets.HTML":
    """Create an assistant message widget with a single tool call."""
    return create_html_widget(
        assistant_message_with_single_tool_html(content, tool_name, tool_args),
        margin="0"
    )