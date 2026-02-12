"""Agent process implementation.

This module defines :class:`AgentProcess`, which runs as a separate
process.  Each agent has an inbound message queue that receives chat
requests from the supervisor.  The agent forwards the request to the
LLM wrapper, streams the response back to the supervisor, and may
generate interjection messages.

The implementation is intentionally lightweight: it focuses on the
core loop and uses :mod:`multiprocessing` primitives so it can be
started from the supervisor.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from multiprocessing import Process, Queue
from typing import Dict, Any
from dataclasses import dataclass

@dataclass
class AgentEvent:
    """Simple event representation used between supervisor and agent.

    Attributes
    ----------
    role:
        Either ``assistant`` or ``user``.
    content:
        The textual content of the message.
    session_id: str | None = None
    agent_id: str | None = None
    type: str | None = None
    prompt: str | None = None
    """

    role: str
    content: str
    token: str | None = None
    session_id: str | None = None
    agent_id: str | None = None
    type: str | None = None
    prompt: str | None = None

# Import the LLM wrapper (will be defined elsewhere)
try:  # pragma: no cover - guard for dev environments
    from .llama_client import LlamaClient
except Exception:  # pragma: no cover
    LlamaClient = None

log = logging.getLogger(__name__)


class AgentProcess(Process):
    """A single agent running in its own process.

    Parameters
    ----------
    agent_id: str
        Identifier used in URLs and logs.
    inbound_queue: Queue
        Queue from which the agent receives chat requests.
    outbound_queue: Queue
        Queue for sending responses back to the supervisor.
    """

    def __init__(self, agent_id: str, inbound_queue: Queue, outbound_queue: Queue, llm_cls: type | None = None):
        super().__init__(name=f"Agent-{agent_id}")
        self.agent_id = agent_id
        self.inbound_queue = inbound_queue
        self.outbound_queue = outbound_queue
        self.llm_cls = llm_cls or LlamaClient
        self.client: LlamaClient | None = None

    def _setup_logging(self) -> None:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            f"[%(asctime)s] [Agent:{self.agent_id}] %(levelname)s: %(message)s"
        )
        handler.setFormatter(formatter)
        log.addHandler(handler)
        log.setLevel(logging.INFO)

    def _initialize_llm(self) -> None:
        if LlamaClient is None:
            raise RuntimeError("LlamaClient not available \u2013 missing llama_client module")
        self.client = LlamaClient()

    def run(self) -> None:  # pragma: no cover – executed in a separate process
        self._setup_logging()
        try:
            self._initialize_llm()
            log.info("Agent process started")
            # Create a single event loop for the whole process
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.create_task(self._main_loop_async())
            self.loop.run_forever()
        except Exception as exc:  # pragma: no cover
            log.exception("Fatal error in agent process: %s", exc)
            sys.exit(1)

    async def _main_loop_async(self) -> None:
        """Async main loop that processes incoming chat messages.

        Uses :func:`asyncio.get_running_loop` and a thread‑safety wrapper
        around the queue's ``get`` method.
        """
        while True:
            event: AgentEvent = await asyncio.get_running_loop().run_in_executor(
                None, self.inbound_queue.get
            )
            if getattr(event, "type", None) == "shutdown":
                log.info("Shutdown signal received")
                self.loop.stop()
                break
            session_id = getattr(event, "session_id", None)
            prompt = getattr(event, "prompt", None)
            if not session_id or not prompt:
                log.warning("Malformed message: %s", event)
                continue
            await self._handle_chat_async(session_id, prompt)

    async def _handle_chat_async(self, session_id: str, prompt: str) -> None:
        """Async version of :meth:`_handle_chat`.

        Runs in the agent's single event loop.
        """
        if self.client is None:
            raise RuntimeError("LLM client not initialized")
        stream_fn = getattr(self.client, "stream_chat", None) or getattr(self.client, "chat", None)
        if stream_fn is None:
            raise RuntimeError("LLM client lacks streaming interface")
        async for token in stream_fn(prompt):
            payload = AgentEvent(
                role="assistant",
                content="",
                token=token,
                session_id=session_id,
                agent_id=self.agent_id,
                type="token",
            )
            self.outbound_queue.put(payload)
        done_event = AgentEvent(
            role="assistant",
            content="",
            session_id=session_id,
            agent_id=self.agent_id,
            type="done",
            prompt=prompt,
        )
        self.outbound_queue.put(done_event)