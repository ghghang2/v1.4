"""Thin wrapper around :mod:`app.db`.

The original repository exposed a :class:`ChatHistory` class used by
the agent process and the FastAPI proxy.  The tests expect this class to
provide :meth:`insert` and :meth:`load_history` methods.  The
implementation simply forwards calls to the module‑level helper
functions defined in :mod:`app.db`.
"""

from . import db


class ChatHistory:
    """Convenience wrapper that mimics the legacy API.

    The wrapper stores no state; each method opens a new database
    connection via :func:`app.db.init_db`.
    """

    def insert(self, session_id: str, role: str, content: str) -> None:
        db.log_message(session_id, role, content)

    def load_history(self, session_id: str, limit: int | None = None):
        return db.load_history(session_id, limit)