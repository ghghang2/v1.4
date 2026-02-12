# Multi-Agent System Implementation Plan

## Overview
This document outlines a step‑by‑step plan to build a minimal‑viable product (MVP) consisting of **one agent** and **one supervisor** that shares a single `llama‑server` instance.  The goal is to create a clean, testable, and maintainable foundation that can be expanded to multiple agents, sophisticated policies, and richer UIs.

The plan is broken into five major phases:
1. Environment & tooling setup
2. Core building blocks (LLM wrapper, persistence, HTTP proxy)
3. Agent implementation (process, inbox, chat logic)
4. Supervisor implementation (event queue, policy hook, interjection)
5. Integration, tests, and documentation

Each phase contains concrete, incremental tasks and the tools we will use.

---

## Phase 1 – Environment & Tooling Setup (Completed)

| Step | Action | Tool | Notes |
|------|--------|------|-------|
| 1.1 | Add `uvicorn` as ASGI server for async components. | | |
| 1.2 | Verify `llama-server` is reachable via a test curl or python request. | | Create a simple `tests/test_llama.py` to hit `/v1/chat/completions`. |
| 1.3 | Set up basic project structure: `app/`, `app/tools/`, `tests/`. | | Already in repo. |

**Deliverables**: Minimal test against `llama-server` passes.

---

## Phase 2 – Core Building Blocks

### 2.1 LLM Wrapper
- **Goal**: A thin, reusable client that talks to `llama-server`.
- Tasks:
  1. Implement `app/llama_client.py` with `class LlamaClient`.
  2. Expose `async def chat(self, prompt: str, session_id: str = None) -> str`.
  3. Handle streaming responses (yield tokens).
  4. Add unit test for happy path and error handling.

### 2.2 Persistence Layer
- **Goal**: Persist chat history in SQLite.
- Tasks:
  1. Implement `app/db.py` with `ChatHistory` class.
  2. Provide `insert(chat_id, role, content)` and `fetch(chat_id)`.
  3. Ensure thread‑safety via connection pooling or `check_same_thread=False`.
  4. Create migration script or `init_db()` function.

### 2.3 HTTP Proxy
- **Goal**: Expose `/chat/{id}` endpoint that forwards to `llama-server`.
- Tasks:
  1. Use Flask or FastAPI to create `app/server.py`.
  2. Accept POST with JSON body `{"prompt": "...", "session_id": "..."}`.
  3. Stream response back to the client.
  4. Write unit tests for proxy logic.

---

## Phase 3 – Agent Implementation

### 3.1 Agent Process
- **Goal**: Each agent runs in its own process with a dedicated inbox queue.
- Tasks:
  1. Implement `app/agent.py` with `class AgentProcess(multiprocessing.Process)`.
  2. Constructor arguments: `agent_id`, `llama_client`, `db`, `inbox_queue`.
  3. `run()` method:
     - Loop: `msg = inbox_queue.get()`.
     - If `msg.type == 'chat'`: load chat history, call LLM, stream response to UI via another queue or callback.
     - If `msg.type == 'interject'`: prepend to conversation and continue.
  4. Provide a simple CLI to send messages to the agent.

### 3.2 Inbox Queue
- Use `multiprocessing.Queue`.
- For persistence, write a small helper `app/queue_persistence.py` that can dump the current state to disk (optional for MVP).

---

## Phase 4 – Supervisor Implementation

### 4.1 Event Queue
- Use a thread‑safe `queue.Queue` inside the supervisor.
- Events are dictionaries: `{"agent_id": str, "role": str, "content": str, "ts": float}`.

### 4.2 Policy Hook
- Implement a simple policy in `app/policy.py`:
  ```python
  def should_interject(event):
      if "ERROR" in event["content"]:
          return "I encountered an error. I will retry the request."
      return None
  ```
- Allow replacing `policy.py` without changing supervisor code.

### 4.3 Supervisor Process
- Implement `app/supervisor.py` with `class SupervisorProcess(multiprocessing.Process)`.
- Constructor arguments: `event_queue`, `agents: Dict[str, AgentProcess]`.
- `run()` loop:
  1. `event = event_queue.get()`.
  2. Call `policy.should_interject(event)`.
  3. If interjection: `agents[event.agent_id].inbox_queue.put(interject_msg)`.
  4. Forward event to the target agent’s inbox.
- Add graceful shutdown: handle `SIGTERM`, propagate to child agents.

---

## Phase 5 – Integration, Tests, Documentation

### 5.1 Integration Tests
- Write `tests/test_integration.py`:
  1. Start `SupervisorProcess`.
  2. Start one `AgentProcess`.
  3. Send a user message via HTTP proxy `/chat/{agent_id}`.
  4. Simulate a policy trigger by injecting an event containing "ERROR".
  5. Assert that the agent receives the interjection before completing the response.

### 5.2 Unit Tests
- Cover:
  - LLM wrapper success and failure.
  - DB insert/fetch.
  - Agent inbox processing.
  - Supervisor policy application.

### 5.3 Documentation
- Update `README.md` with:
  - High‑level architecture diagram.
  - Setup instructions.
  - How to run the MVP.
  - How to add more agents.
- Generate `repo_overview.md` using the existing tool.

---

## Timeline & Milestones
| Milestone | Description | Target |
|-----------|-------------|--------|
| 1 | Environment & test against llama-server | Day 1 |
| 2 | LLM wrapper + DB + proxy | Day 2-3 |
| 3 | Agent process + inbox | Day 4 |
| 4 | Supervisor + policy | Day 5 |
| 5 | Integration test & documentation | Day 6 |
| 6 | CI & final review | Day 7 |

---

## Risks & Mitigations
| Risk | Impact | Mitigation |
| 1 | LLM server may not support session IDs | Wrap prompts with unique agent token; test thoroughly |
| 2 | Queue deadlock in multi‑process setup | Use bounded queues; add timeouts |
| 3 | Performance bottleneck on single GPU | Keep LLM requests async; limit concurrency |
| 4 | Supervisor may miss interjections | Log all events; add unit tests for policy path |

---
