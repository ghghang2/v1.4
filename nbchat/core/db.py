"""Database helper wrappers.

The original database logic resides in :mod:`app.db`.  This module
provides thin wrappers so that the UI and conversation code can
import from ``nbchat.core.db`` instead.
"""

from __future__ import annotations

from typing import Any, List, Tuple

import app.db as _db


def init_db() -> None:
    """Initialize the SQLite database if it does not exist."""
    _db.init_db()


def log_message(session_id: str, role: str, content: str) -> None:
    """Persist a message to the database."""
    _db.log_message(session_id, role, content)


def log_tool_msg(session_id: str, tool_id: str, tool_name: str, tool_args: str, result: str) -> None:
    """Persist a tool execution result to the database."""
    _db.log_tool_msg(session_id, tool_id, tool_name, tool_args, result)


def load_history(session_id: str) -> List[Tuple[str, str]]:
    """Return the list of (role, content) tuples for a session."""
    return _db.load_history(session_id)


def get_session_ids() -> List[str]:
    """Return the list of session identifiers."""
    return _db.get_session_ids()
