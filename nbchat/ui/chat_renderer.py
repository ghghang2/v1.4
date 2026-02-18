"""Central widget rendering utilities for nbchat.

This module consolidates all the HTML‑generation logic that was previously
spread across :mod:`nbchat.ui.chatui` and :mod:`nbchat.ui.styles`.  The goal
is to expose a small, easy‑to‑use API that returns ``ipywidgets.HTML``
instances for the various roles that appear in a chat session.

Only the minimal set of functions required by the current UI are provided.
If a new role is added in the future it can be added here without touching the
rest of the code base.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import ipywidgets as widgets

# Import styling helpers.  These helpers return plain HTML strings.
from nbchat.ui.styles import (
    user_message_html,
    assistant_message_html,
    reasoning_html,
    tool_result_html,
    assistant_message_with_tools_html,
    assistant_message_with_single_tool_html,
    assistant_full_html,
    create_html_widget,
)

__all__ = [
    "render_user",
    "render_assistant",
    "render_reasoning",
    "render_tool",
    "render_assistant_with_tools",
    "render_assistant_with_single_tool",
    "render_assistant_full",
    "render_system",
    "render_placeholder",
]


def _widget(html: str, width: str = "100%", margin: str = "0") -> widgets.HTML:
    """Create an ``ipywidgets.HTML`` from raw HTML.

    Parameters
    ----------
    html:
        Raw HTML string.
    width:
        Width of the widget (default: ``"100%"``).
    margin:
        CSS margin for the widget (default: ``"0"``).
    """

    return create_html_widget(html, width=width, margin=margin)


# ---------------------------------------------------------------------------
# Public rendering helpers
# ---------------------------------------------------------------------------

def render_user(content: str) -> widgets.HTML:
    """Render a user message.

    The content is processed as Markdown by :func:`nbchat.core.utils.md_to_html`
    inside :func:`nbchat.ui.styles.user_message_html`.
    """

    html = user_message_html(content)
    return _widget(html)


def render_assistant(content: str) -> widgets.HTML:
    """Render a plain assistant message."""

    html = assistant_message_html(content)
    return _widget(html)


def render_reasoning(content: str, open: bool = True) -> widgets.HTML:
    """Render a collapsible reasoning block.

    Parameters
    ----------
    content:
        The reasoning text.
    open:
        If ``True`` the ``<details>`` element is rendered with the ``open``
        attribute so the content is shown by default.
    """

    html = reasoning_html(content, open=open)
    return _widget(html)


def render_tool(content: str, tool_name: str, preview: Optional[str] = None) -> widgets.HTML:
    """Render a tool result.

    ``preview`` is a short excerpt shown in the collapsed summary.
    If ``None`` the first 50 characters of ``content`` are used.
    """

    html = tool_result_html(content, tool_name=tool_name, preview=preview)
    return _widget(html)


def render_assistant_with_tools(content: str, tool_calls: List[Dict[str, Any]]) -> widgets.HTML:
    """Render an assistant message that includes multiple tool calls.

    ``tool_calls`` should be a list of the same structure that the OpenAI API
    returns – each element has a ``function`` dict with ``name`` and
    ``arguments`` keys.
    """

    html = assistant_message_with_tools_html(content, tool_calls)
    return _widget(html)


def render_assistant_with_single_tool(content: str, tool_name: str, tool_args: str) -> widgets.HTML:
    """Render an assistant message that contains a single tool call."""

    html = assistant_message_with_single_tool_html(content, tool_name, tool_args)
    return _widget(html)


def render_assistant_full(
    reasoning: str, content: str, tool_calls: List[Dict[str, Any]]
) -> widgets.HTML:
    """Render the *assistant_full* message used during streaming.

    The assistant_full message is a full snapshot containing the reasoning
    block, the assistant content and any pending tool calls.
    """

    html = assistant_full_html(reasoning, content, tool_calls)
    return _widget(html)


def render_system(content: str) -> widgets.HTML:
    """Render a system message (currently unused but kept for completeness)."""

    # System messages are rendered as a plain HTML block with the system
    # prefix.  The styling is minimal and follows the same layout as other
    # messages.
    from nbchat.ui.styles import system_style_dict

    style = "; ".join(f"{k}: {v}" for k, v in system_style_dict().items())
    html = f"<b>System:</b> {content}"
    return _widget(html, width="100%", margin="0")


def render_placeholder(role: str) -> widgets.HTML:
    """Return a minimal placeholder for a streaming role.

    Parameters
    ----------
    role:
        One of ``"assistant"`` or ``"reasoning"``.
    """

    if role == "assistant":
        html = assistant_message_html("")  # empty content
    elif role == "reasoning":
        html = reasoning_html("")  # empty, collapsible
    else:
        raise ValueError(f"Unknown placeholder role: {role}")
    return _widget(html)
