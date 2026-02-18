# nbchat UI Refactor Plan

## Objectives

1. **Keep the UI fully functional** – the chat history, streaming of assistant replies, tool execution, and server‑status metrics must remain unchanged from the user’s perspective.
2. **Reduce code duplication** – many rendering helpers and style dictionaries are repeated.
3. **Improve maintainability** – isolate responsibilities (rendering, message building, tool execution, metrics polling) into small, well‑named modules.
4. **Preserve minimal styling** – the look must stay compact and clean; only the structure of the code changes.
5. **Maintain collapsible reasoning blocks** – reasoning should stay collapsible, but can share a common widget with assistant content when convenient.
6. **Keep the metrics thread updating once per second** – near real‑time feedback is required.
7. **Avoid creating a new `ThreadPoolExecutor` per tool call** – reuse a single executor.
8. **Cache style strings** – compute CSS once instead of on every render.
9. **Simplify the widget factory** – one rendering function per role instead of many small ones.
10. **Separate model interaction from UI** – build OpenAI message lists in a dedicated helper.

## High‑Level Tasks

| # | Task | Description | Owner | Status |
|---|------|-------------|-------|--------|
| 1 | Create `chat_renderer.py` | Central widget factory: `render_widget(role, content, tool_info=None)` that returns `ipywidgets.HTML`. | me | **DONE** |
 | 2 | Extract message builder | Function `build_messages(history, system_prompt) -> List[Dict]` that converts internal history into LLM‑friendly format. | me | **DONE** |
| 3 | Refactor `ChatUI` core | Replace `_render_*` methods, `_process_conversation_turn`, and UI update logic with calls to the new renderer and builder. | me | TODO |
| 4 | Consolidate styling | Keep a single `STYLE_MAP` dict mapping roles to style strings; compute CSS once. | me | TODO |
| 5 | Simplify tool execution | Create a module `tool_executor.py` with a single `ThreadPoolExecutor` and a `run_tool(name, args)` helper. | me | TODO |
| 6 | Re‑implement metrics thread | Move to a `metrics_updater.py` that spawns a daemon thread updating `metrics_output` every second. | me | TODO |
| 7 | Update tests | Verify that the refactor does not break any tests. | me | TODO |
| 8 | Add documentation | Update README and inline docs to reflect new architecture. | me | TODO |
| 9 | Code cleanup | Remove unused imports, add type hints, and run `black` / `isort`. | me | TODO |

## Deliverables

1. `refactor_plan.md` (this file).
2. `chat_renderer.py` – rendering utilities.
3. `chat_builder.py` – history → messages conversion.
4. `tool_executor.py` – single executor for all tool calls.
5. `metrics_updater.py` – per‑second metrics thread.
6. Updated `ChatUI` with minimal widget creation and streaming logic.
7. Updated `styles.py` to use cached CSS strings.
8. Updated tests to cover new modules.

## Milestones

- **Week 1** – Implement rendering factory and style cache; refactor `ChatUI` to use it. *Target: 100% of rendering logic moved.*
- **Week 2** – Extract message builder and tool executor; update streaming logic. *Target: all tool calls use new executor.*
- **Week 3** – Implement metrics updater thread; run full test suite. *Target: no failing tests.*
- **Week 4** – Documentation, linting, and final cleanup. *Target: code passes `flake8`, `black`, and `isort`.*

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking the UI flow during refactor | Medium | Run interactive tests after each commit; keep a copy of the original `ChatUI` to rollback if needed. |
| Incorrectly handling reasoning collapsibility | Low | Keep the same `<details>`/`<summary>` structure; unit‑test that the HTML renders as expected. |
| Metrics thread missing updates | Low | Keep the same 1 s sleep loop; verify `metrics_output` changes every second with a quick script. |

---

Feel free to tweak the plan as we progress.
