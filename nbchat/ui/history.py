"""History persistence and rendering helpers.

The legacy code kept all history logic inside ``ChatUI``.  After the
refactor this module contains only small, pure functions that can be
unit‑tested.
"""

from __future__ import annotations

from typing import List, Tuple

import ipywidgets as widgets
from nbchat.core import db as _db
from nbchat.core.utils import md_to_html

# ----------------------------------------------------------------------
def load_history(session_id: str) -> List[Tuple[str, str, str, str, str]]:
    """Return a list of history entries for *session_id*.

    The database stores only ``role`` and ``content``.  The helper
    expands each entry into the tuple format expected by the UI:
    ``(role, content, tool_id, tool_name, tool_args)``.
    """

    rows = _db.load_history(session_id)
    # Each row is (role, content)
    return [(role, content, "", "", "") for role, content in rows]


# ----------------------------------------------------------------------
def _render_user_message(content: str) -> widgets.HTML:
    return widgets.HTML(
        value=f'<div style="background-color: #e3f2fd; padding: 0px; border-radius: 5px; margin: 0;">{md_to_html(content)}</div>',
        layout=widgets.Layout(width="100%", margin="0"),
    )


def _render_assistant_message(content: str) -> widgets.HTML:
    return widgets.HTML(
        value=f'<div style="background-color: #f1f8e9; padding: 0px; border-radius: 5px; margin: 0;">{md_to_html(content)}</div>',
        layout=widgets.Layout(width="100%", margin="0"),
    )


def render_history(history: List[Tuple[str, str, str, str, str]]) -> List[widgets.Widget]:
    """Return a list of widgets representing *history*.

    This function is intentionally simple – it only supports user and
    assistant messages.  The original implementation handled tool
    messages and reasoning; that complexity can be re‑added later.
    """

    widgets_list: List[widgets.Widget] = []
    for role, content, *_ in history:
        if role == "user":
            widgets_list.append(_render_user_message(content))
        elif role == "assistant":
            widgets_list.append(_render_assistant_message(content))
        # Other roles are ignored for brevity.
    return widgets_list
