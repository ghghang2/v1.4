"""Persist chat history in a lightweight SQLite database.

The database is created in the repository root as ``chat_history.db``.
It contains a single table ``chat_log`` which stores every user and
assistant message together with a session identifier.

Context summaries produced by the compaction engine are stored as rows
with ``role = 'context_summary'``.  There is at most one such row per
session; ``save_context_summary`` replaces any existing one.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "chat_history.db"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection | None = None) -> None:
    """Create the database and tables if they do not exist.

    Idempotent — safe to call on every application startup.
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
                    tool_name   TEXT,
                    tool_args   TEXT,
                    ts          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_session ON chat_log(session_id);"
            )
            # Separate table for per-session metadata (e.g. context summaries)
            # so they never interfere with ordered history reconstruction.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_meta (
                    session_id  TEXT NOT NULL,
                    key         TEXT NOT NULL,
                    value       TEXT,
                    ts          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (session_id, key)
                );
                """
            )
            conn.commit()


# ---------------------------------------------------------------------------
# Chat log helpers
# ---------------------------------------------------------------------------

def log_message(session_id: str, role: str, content: str) -> None:
    """Persist a single chat line (user or assistant text)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO chat_log (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )
        conn.commit()


def log_tool_msg(
    session_id: str,
    tool_id: str,
    tool_name: str,
    tool_args: str,
    content: str,
) -> None:
    """Persist a tool result row with its associated metadata."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO chat_log
                (session_id, role, content, tool_id, tool_name, tool_args)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, "tool", content, tool_id, tool_name, tool_args),
        )
        conn.commit()


def load_history(
    session_id: str,
    limit: int | None = None,
) -> list[tuple[str, str, str, str, str]]:
    """Return chat rows for *session_id* in insertion order.

    Returns tuples of ``(role, content, tool_id, tool_name, tool_args)``.
    """
    with sqlite3.connect(DB_PATH) as conn:
        query = (
            "SELECT role, content,"
            " COALESCE(tool_id, ''),"
            " COALESCE(tool_name, ''),"
            " COALESCE(tool_args, '')"
            " FROM chat_log"
            " WHERE session_id = ?"
            " ORDER BY id ASC"
        )
        params: list = [session_id]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        cur = conn.execute(query, params)
        return cur.fetchall()


def get_session_ids() -> list[str]:
    """Return all distinct session IDs ordered by most recent activity."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "SELECT DISTINCT session_id FROM chat_log ORDER BY ts DESC"
        )
        return [row[0] for row in cur.fetchall()]


def replace_session_history(
    session_id: str,
    history: list[tuple[str, str, str, str, str]],
) -> None:
    """Atomically replace all chat_log rows for *session_id*.

    Used by the compaction engine after it trims older turns.  The context
    summary is stored separately via ``save_context_summary`` and is
    therefore unaffected by this call.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM chat_log WHERE session_id = ?", (session_id,))
        conn.executemany(
            """
            INSERT INTO chat_log
                (session_id, role, content, tool_id, tool_name, tool_args)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (session_id, r, c, tid, tname, targs)
                for r, c, tid, tname, targs in history
            ],
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Context summary helpers
# ---------------------------------------------------------------------------

def save_context_summary(session_id: str, summary: str) -> None:
    """Upsert the rolling context summary for *session_id*.

    There is at most one summary row per session; this replaces any
    previously stored value.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO session_meta (session_id, key, value, ts)
            VALUES (?, 'context_summary', ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id, key) DO UPDATE SET
                value = excluded.value,
                ts    = excluded.ts
            """,
            (session_id, summary),
        )
        conn.commit()


def load_context_summary(session_id: str) -> str:
    """Return the stored context summary for *session_id*, or ``""``."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "SELECT value FROM session_meta WHERE session_id = ? AND key = 'context_summary'",
            (session_id,),
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else ""