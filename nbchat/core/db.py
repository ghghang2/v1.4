# app/db.py
"""Persist chat history in a lightweight SQLite database.

The database is created in the repository root as ``chat_history.db``.
It contains a single table ``chat_log`` which stores every user and
assistant message together with a session identifier.  The schema is
minimal but sufficient to reconstruct a conversation on page reload.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime

# Location of the database file – one level up from this module
DB_PATH = Path(__file__).resolve().parent.parent / "chat_history.db"

# Optional in‑memory connection used by tests
_conn: sqlite3.Connection | None = None

def _get_conn() -> sqlite3.Connection:
    if _conn is not None:
        return _conn
    return sqlite3.connect(DB_PATH)

# ---------------------------------------------------------------------------
#  Public helpers
# ---------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection | None = None) -> None:
    """Create the database file and the chat_log table if they do not exist.

    The function is idempotent – calling it repeatedly has no adverse
    effect.  It should be invoked once during application startup.
    """
    if conn is None:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT,
                tool_id     TEXT,
                tool_name     TEXT,
                tool_args     TEXT,
                ts          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        # Optional index – speeds up SELECTs filtered by session_id.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON chat_log(session_id);")
        conn.commit()


def log_message(session_id: str, role: str, content: str) -> None:
    """Persist a single chat line.

    Parameters
    ----------
    session_id
        Identifier of the chat session – e.g. a user ID or a UUID.
    role
        .
    content
        The raw text sent or received.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO chat_log (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )
        conn.commit()

def log_tool_msg(session_id: str, tool_id: str, tool_name: str, tool_args: str, content: str) -> None:
    """Persist a single chat line.

    Parameters
    ----------
    session_id
        Identifier of the chat session – e.g. a user ID or a UUID.
    role
        .
    content
        The raw text sent or received.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO chat_log (session_id, role, content, tool_id, tool_name, tool_args) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, 'assistant', '', tool_id, tool_name, tool_args),
        )
        conn.execute(
            "INSERT INTO chat_log (session_id, role, content, tool_id) VALUES (?, ?, ?, ?)",
            (session_id, 'tool', content, tool_id),
        )
        conn.commit()


def load_history(session_id: str, limit: int | None = None) -> list[tuple[str, str, str, str, str]]:
    """Return the last *limit* chat pairs for the given session.

    The returned list contains tuples of ``(role, content, tool_id, tool_name, tool_args)`` in the order
    they were inserted.  ``limit`` is applied to the number of rows
    returned.
    """
    import sys
    print(f"[DEBUG] DB_PATH: {DB_PATH}, exists: {DB_PATH.exists()}", file=sys.stderr)
    rows: list[tuple[str, str, str, str, str]] = []
    with sqlite3.connect(DB_PATH) as conn:
        query = "SELECT role, content, COALESCE(tool_id, ''), COALESCE(tool_name, ''), COALESCE(tool_args, '') FROM chat_log WHERE session_id = ? ORDER BY id ASC"
        params = [session_id]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        import sys
        print(f"[DEBUG] query: {query}, params: {params}", file=sys.stderr)
        cur = conn.execute(query, params)
        rows = cur.fetchall()
        print(f"[DEBUG] fetched {len(rows)} rows", file=sys.stderr)
    return rows


def get_session_ids() -> list[str]:
    """Return a list of all distinct session identifiers stored in the DB."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT DISTINCT session_id FROM chat_log ORDER BY ts DESC")
        return [row[0] for row in cur.fetchall()]