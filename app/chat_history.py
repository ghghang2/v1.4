"""Thin wrapper around :mod:`app.db`.

The test suite imports :mod:`app.server` and expects a module named
``chat_history`` that exposes ``insert`` and ``load_history``.  The real
database logic lives in :mod:`app.db`; this module simply re‑exports
the relevant functions.
"""

from .db import log_message as insert, load_history
