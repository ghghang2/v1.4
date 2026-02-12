"""Tests for the SQLite persistence layer in :mod:`app.db`.

The tests create an in‑memory database, insert a few messages, and
verify that they can be retrieved in the correct order.
"""

import sqlite3
import pytest

from app import db


def get_in_memory_db():
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    return conn


def test_log_and_load_history():
    db.init_db()  # use the module level init function
    chat_history = db.ChatHistory()
    # Insert messages
    chat_history.insert("sess1", "user", "Hello")
    chat_history.insert("sess1", "assistant", "Hi")
    chat_history.insert("sess2", "user", "Foo")
    # Load history for sess1
    history = chat_history.load_history("sess1")
    assert history == [("user", "Hello"), ("assistant", "Hi")]
    # Load history for sess2
    history2 = chat_history.load_history("sess2")
    assert history2 == [("user", "Foo")]
