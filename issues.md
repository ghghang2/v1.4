# Existing Bugs and Issues

## Priority: Critical

### Security: Hardcoded API Key (`nbchat/core/client.py`)
*   **Issue:** API key committed in source code.
*   **Impact:** Unauthorized API usage, potential billing fraud.
*   **Fix:** Move to environment variable (e.g., `DEEPSEEK_API_KEY`).

## Priority: High

### Database: `init_db` Indentation Bug (`nbchat/core/db.py`)
*   **Issue:** `CREATE INDEX` and `conn.commit()` are outside the `with` block; `conn` is undefined.
*   **Impact:** `init_db` raises an exception, breaking database initialization.
*   **Fix:** Indent those two lines inside the `with` block.

### Thread Safety: Race Conditions in UI (`nbchat/ui/chatui.py`)
*   **Issue:** `self.chat_history.children` accessed/modified from streaming thread without lock.
*   **Impact:** UI corruption, inconsistent state.
*   **Fix:** Use `threading.Lock` around all accesses or ensure UI updates are serialized.

### Run Script: Missing `errno` Import (`run.py`)
*   **Issue:** `except OSError` block references `errno.ESRCH` without importing `errno`.
*   **Impact:** `NameError` when trying to stop a dead process, leaving services in an undefined state.
*   **Fix:** Add `import errno` at the top of the file.

## Priority: Medium

### Database: Incomplete Docstrings (`nbchat/core/db.py`)
*   **Issue:** `log_message` and `log_tool_msg` have placeholder descriptions (`role\n        .`).
*   **Impact:** Confusing documentation.
*   **Fix:** Update docstrings with proper parameter descriptions.

### Database: `log_tool_msg` Signature vs. Documentation
*   **Issue:** Docstring mentions a `role` parameter, but function signature does not have one.
*   **Impact:** Misleading documentation.
*   **Fix:** Align docstring with actual signature.

### Database: Duplicate `import sys` (`nbchat/core/db.py`)
*   **Issue:** Unused `import sys` appears twice in `load_history`.
*   **Impact:** Minor code clutter.
*   **Fix:** Remove the duplicate import.

### Configuration: Unused Import (`nbchat/core/config.py`)
*   **Issue:** `from nbchat.tools.repo_overview import func` leftover.
*   **Impact:** Unnecessary dependency.
*   **Fix:** Remove the import.

### Utilities: Inconsistent Lazy Import Return Types (`nbchat/core/utils.py`)
*   **Issue:** `lazy_import` returns a function call for some modules, the module object for others.
*   **Impact:** Callers must know the semantics, leading to potential errors.
*   **Fix:** Make return type consistent (e.g., always return the module).

### UI Styling: Potentially Buggy Regex (`nbchat/ui/styles.py`)
*   **Issue:** Regex `<p(?!re)[^>]*>` may incorrectly skip `<p>` tags with attributes containing "re".
*   **Impact:** Minor visual rendering issue.
*   **Fix:** Use a more robust pattern (e.g., `<p(?!\\s*re)[^>]*>`).

### UI Styling: Tool Result Summary Formatting (`nbchat/ui/styles.py`)
*   **Issue:** Label omitted when `tool_args` is empty, causing leading pipe (`|`) in summary.
*   **Impact:** Visual glitch.
*   **Fix:** Always include label, join parts only when non‑empty.

### UI Core: Duplicate Logging (`nbchat/ui/chatui.py`)
*   **Issue:** Both `db.log_message` and `db.log_tool_msg` called for the same assistant message.
*   **Impact:** Duplicate rows in chat history.
*   **Fix:** Ensure each turn logs only once.

### UI Core: Metrics Updater May Crash on Git Errors (`nbchat/ui/chatui.py`)
*   **Issue:** `changed_files()` uses `subprocess.check_output` without handling `CalledProcessError`.
*   **Impact:** Repeated exceptions in the metrics updater thread.
*   **Fix:** Wrap git calls in try‑except.

### UI Core: `_refresh_tools_list` Expects Specific Tool Format (`nbchat/ui/chatui.py`)
*   **Issue:** Assumes each tool dict has `["function"]["name"]`; brittle if tool format changes.
*   **Impact:** UI may break if tool schema evolves.
*   **Fix:** Use a more defensive access pattern.

### UI Core: `_stream_response` Assumptions About Tool Call Index (`nbchat/ui/chatui.py`)
*   **Issue:** Relies on `tc.index` being unique and arriving in order.
*   **Impact:** Could break with malformed stream responses.
*   **Fix:** Add robustness checks.

### UI Core: `self._stop_streaming` Flag Not Atomic (`nbchat/ui/chatui.py`)
*   **Issue:** Flag read/written from multiple threads without synchronization.
*   **Impact:** Potential race condition causing missed stops.
*   **Fix:** Use `threading.Event`.

### Chat Builder: Special `tool_id` Values Not Handled (`nbchat/ui/chat_builder.py`)
*   **Issue:** `tool_id == "multiple"` is not handled; builder treats it as a single tool call.
*   **Impact:** Mismatch between UI rendering and API messages.
*   **Fix:** Add a dedicated case for `"multiple"` or store tool calls differently.

### Run Script: Incorrect `os.killpg` Usage (`run.py`)
*   **Issue:** `os.killpg(pid, signal.SIGTERM)` called with a process ID, not a process group ID.
*   **Impact:** May still work if the process is the group leader, but misleading.
*   **Fix:** Use `os.kill` or obtain the process group ID.

### Run Script: Placeholder PIDs Saved as Strings (`run.py`)
*   **Issue:** `"streamlit_proc.pid"` and `"ngrok_proc.pid"` stored as strings instead of actual PIDs.
*   **Impact:** `status()` and `stop()` will attempt to kill non‑numeric PIDs, causing errors.
*   **Fix:** Store real PIDs or remove placeholders.

## Priority: Low

### General: Lack of Unit Tests
*   **Issue:** No test suite found.
*   **Impact:** Increased risk of regression.
*   **Fix:** Introduce basic pytest suite.

### General: Inconsistent Error Handling
*   **Issue:** Some functions catch generic `Exception`, others let exceptions propagate.
*   **Impact:** Inconsistent error reporting.
*   **Fix:** Standardize error‑handling approach.

### Dependencies: Missing in `requirements.txt`
*   **Issue:** `ipywidgets` and `IPython` are required but not listed.
*   **Impact:** Installation may fail in fresh environments.
*   **Fix:** Add missing dependencies.

## Summary

*   **Critical:** 1 issue (security).
*   **High:** 3 issues (database init, thread safety, missing import).
*   **Medium:** 14 issues (code quality, UI bugs, run script).
*   **Low:** 3 issues (tests, error handling, dependencies).

> **Note:** This list focuses on `nbchat/core` and `nbchat/ui` directories, excluding tool‑specific files as requested.

