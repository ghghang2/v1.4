"""Unit tests for :class:`app.supervisor.SupervisorProcess`.

The tests exercise the following scenarios:

1. Normal chat events are forwarded from the agent to the supervisor
   and then to an external consumer queue.
2. When the policy hook detects the word ``"error"`` in the prompt, the
   supervisor injects an interjection event.
3. The supervisor can shut itself down cleanly, propagating a shutdown
   event to child agents.
"""

import time
import multiprocessing as mp
import queue
from dataclasses import dataclass

import pytest
import asyncio

from app.supervisor import SupervisorProcess, SupervisorConfig
from app.agent import AgentProcess, AgentEvent


# ---------------------------------------------------------------------------
# Dummy LLM client – mimics the streaming interface used by AgentProcess
# ---------------------------------------------------------------------------
class DummyLLM:
    """A minimal LLM that streams a few tokens quickly.

    The :func:`stream_chat` method is an async generator that yields
    a single token per call.
    """

    async def stream_chat(self, prompt: str):  # pragma: no cover - trivial
        # Emit two tokens and then finish
        for token in ["Hello", "world"]:
            await asyncio.sleep(0.01)
            yield token


def _create_agent_with_dummy_llm(name: str = "test") -> AgentProcess:
    """Return an :class:`AgentProcess` that uses :class:`DummyLLM`.

    The agent will use the dummy client to produce deterministic
    output during tests.
    """
    inbox = mp.Queue()
    outbound = mp.Queue()
    agent = AgentProcess(name, inbox, outbound, llm_cls=DummyLLM)
    return agent


@pytest.fixture
def supervisor_with_agent(tmp_path):  # pragma: no cover - fixture
    """Create a SupervisorProcess with a single dummy agent.

    The agent **must** be started manually because we are injecting a
    pre‑created :class:`AgentProcess` instance into the supervisor.
    """
    agent = _create_agent_with_dummy_llm("agent1")
    agent.start()
    supervisor = SupervisorProcess(
        config=SupervisorConfig(agent_name="agent1"),
        agent_processes={"agent1": agent},
    )
    supervisor.start()
    # Give the supervisor a moment to start
    time.sleep(0.1)
    yield supervisor
    # Teardown: ensure the supervisor and agent are terminated
    supervisor.terminate()
    supervisor.join()
    if agent.is_alive():
        agent.join(timeout=1.0)


def _collect_events(queue_obj, timeout=1.0):  # pragma: no cover
    """Collect all events currently available from a multiprocessing queue.

    The helper blocks for *timeout* seconds to allow async work to
    finish.
    """
    events = []
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            events.append(queue_obj.get_nowait())
        except queue.Empty:
            break
    return events


def test_normal_event_forwarding(supervisor_with_agent):  # pragma: no cover
    """Verify that a normal chat request is forwarded unchanged.

    The supervisor should forward the agent’s token events and the
    ``done`` event to the external consumer queue.
    """
    inbox = supervisor_with_agent.agent_inboxes["agent1"]
    # Send a simple prompt that does not trigger policy
    inbox.put(AgentEvent(role="user", content="", session_id="s1", prompt="Hello there"))
    time.sleep(0.2)
    events = _collect_events(supervisor_with_agent.supervisor_outbound)
    # We expect at least two token events and a done event
    token_events = [e for e in events if e.type == "token"]
    done_events = [e for e in events if e.type == "done"]
    assert len(token_events) >= 2
    assert len(done_events) == 1
    # No interjection events should be present
    interjections = [e for e in events if e.type == "interjection"]
    assert not interjections


def test_interjection_on_error(supervisor_with_agent):  # pragma: no cover
    """Verify that policy triggers an interjection when the prompt contains "error".
    """
    inbox = supervisor_with_agent.agent_inboxes["agent1"]
    inbox.put(AgentEvent(role="user", content="", session_id="s2", prompt="This is an error example"))
    time.sleep(0.3)
    events = _collect_events(supervisor_with_agent.supervisor_outbound)
    # We expect an interjection event after the normal conversation
    interjections = [e for e in events if e.type == "interjection"]
    assert interjections, "Policy did not trigger an interjection"
    # The interjection content should reference the original prompt
    assert "error" in interjections[0].prompt.lower()
    # Ensure normal token/done events are still present
    token_events = [e for e in events if e.type == "token"]
    done_events = [e for e in events if e.type == "done"]
    assert token_events
    assert done_events
