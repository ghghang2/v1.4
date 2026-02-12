"""Tests for the FastAPI proxy in :mod:`app.server`.

The proxy streams tokens from a dummy LLM client and persists the
interaction via :mod:`app.chat_history`.  We patch both the LLM client
and the chat history logger to capture the interactions without
requiring a real database or llama‑server.
"""

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app import server, chat_history, db


async def dummy_stream(prompt: str, session_id: str):
    """Yield a fixed set of tokens for the given prompt.

    The real ``LlamaClient`` exposes an async generator.  In the tests we
    provide a deterministic generator so the output is predictable.
    """

    for token in ["Hello", " ", "world", "!"]:
        await asyncio.sleep(0.01)
        yield token


def test_proxy_stream_and_logging(tmp_path, monkeypatch):
    # Patch the LLM client used by the server
    dummy_client = MagicMock()
    dummy_client.stream_chat = dummy_stream
    monkeypatch.setattr(server, "llama_client", dummy_client)

    # Patch the chat history insert to capture calls
    insert_calls = []
    def fake_insert(session_id, role, content):
        insert_calls.append((session_id, role, content))

    monkeypatch.setattr(chat_history, "insert", fake_insert)

    client = TestClient(server.app)
    payload = {"prompt": "hi", "session_id": "sess1"}
    response = client.post("/chat/test_agent", json=payload)

    # Collect streamed chunks from the response body
    streamed = "".join(chunk.decode() for chunk in response.iter_text())
    assert streamed == "Hello world!"

    # Verify that the user message was logged
    assert any(call[1] == "user" and call[0] == "sess1" for call in insert_calls)
    # Verify that each assistant token was logged
    assistant_calls = [c for c in insert_calls if c[1] == "assistant"]
    assert [c[2] for c in assistant_calls] == ["Hello", " ", "world", "!"]
