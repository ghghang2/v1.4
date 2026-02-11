Ticket 0002: Refactor UI from Streamlit to a lightweight Python web framework

**Status**: In Progress

**Goal**: Replace Streamlit‑based UI with FastAPI + Jinja2 + SSE, removing Streamlit and reducing dependencies.

**Key Steps**:
1. Remove Streamlit imports from `app/chat.py` and `app/metrics_ui.py`.
2. Create `app/main.py` with FastAPI endpoints.
3. Add `templates/chat.html` and `templates/metrics.html`.
4. Move metrics logic to `app/metrics.py` as an async task.
5. Update `run.py` to launch Uvicorn.
6. Adjust `requirements.txt`.
7. Add tests.

**Acceptance**: No Streamlit code, chat streaming works, metrics page updates, tests pass.