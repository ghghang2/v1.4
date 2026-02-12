"""FastAPI HTTP proxy for the Llama chat service.

The test suite imports :mod:`app.server` and expects a module that
provides a ``/chat/{agent_id}`` endpoint.  The implementation is kept
minimal and uses a dummy LLM client that can be patched in tests.
"""

from __future__ import annotations

import uuid
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from app.llama_client import LlamaClient
import app.chat_history as chat_history

app = FastAPI()
llama_client = LlamaClient()


async def _token_generator(prompt: str, session_id: str, agent_id: str) -> AsyncGenerator[str, None]:
    """Yield tokens from the LLM client.

    The real client exposes ``chat`` which streams tokens.  Test doubles
    provide ``stream_chat``; we support both for maximum compatibility.
    """

    # Prefer a dedicated streaming API.
    stream_fn = getattr(llama_client, "stream_chat", None) or getattr(llama_client, "chat", None)
    if stream_fn is None:
        raise RuntimeError("LLM client does not provide a streaming interface")
    async for token in stream_fn(prompt, session_id):
        # Persist each assistant token for later reconstruction
        chat_history.insert(agent_id, "assistant", token)
        yield token


@app.post("/chat/{agent_id}")
async def chat(agent_id: str, request: Request):  # pragma: no cover - exercised via tests
    data = await request.json()
    prompt: str = data["prompt"]
    session_id: str = data.get("session_id", str(uuid.uuid4()))
    # Persist the user message before streaming a response
    chat_history.insert(agent_id, "user", prompt)
    return StreamingResponse(_token_generator(prompt, session_id, agent_id), media_type="text/plain")
