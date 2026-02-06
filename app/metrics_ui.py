"""Streamlit UI for displaying Llama server metrics.

The upstream project had a more elaborate implementation that started a
thread at import time.  That caused the Streamlit app to block because the
worker attempted to update a placeholder that did not exist yet.
This module provides a clean, test‑friendly implementation:

* :func:`parse_log` reads the log file and extracts two pieces of
  information — whether the server is still processing a request and the
  current *tokens per second* (TPS) value.
* :func:`display_metrics_panel` is called from :mod:`app` inside a sidebar
  context.  It creates a placeholder and starts a background worker that
  updates the placeholder every second.

The worker uses the placeholder passed as an argument, so the placeholder
must be created inside the function — this avoids a global variable.
"""

from __future__ import annotations

import re
import time
import threading
from pathlib import Path
from typing import Tuple

import streamlit as st

TOKENS_PER_SEC_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s+tokens per second", re.IGNORECASE
)


def parse_log(path_string: str) -> Tuple[bool | None, float | None]:
    """Parse *llama_server.log*.

    Returns a tuple ``(is_processing, tps)``.  ``is_processing`` is
    ``True`` when a line containing ``slot update_slots`` is found, ``False``
    when the line ``srv  update_slots: all slots are idle`` appears.  The
    first matching line from the end of the file is used.  ``tps`` is the
    number extracted from the most recent ``eval time`` line.
    """

    log_path = Path(path_string)
    if not log_path.exists():
        raise FileNotFoundError(f"Log file not found: {log_path}")

    with log_path.open("r", encoding="utf-8") as fp:
        lines = fp.readlines()

    is_processing: bool | None = None
    tps: float | None = None

    for raw_line in reversed(lines):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        if re.search(r"slot update_slots:", raw_line, re.IGNORECASE):
            is_processing = True
            break
        if raw_line.lower() == "srv  update_slots: all slots are idle":
            is_processing = False
            break

    for raw_line in reversed(lines):
        if re.search(r"eval time", raw_line, re.IGNORECASE):
            m = TOKENS_PER_SEC_RE.search(raw_line)
            if m:
                tps = float(m.group("value"))
                break

    return is_processing, tps


def _metrics_worker(placeholder: st.delta_generator.DeltaGenerator) -> None:
    """Background thread that polls the log and updates *placeholder*.

    The thread loops forever, sleeping one second between polls.  It
    never raises; any exception results in a ``None`` value.
    """

    while True:
        try:
            processing, prediction_tps = parse_log("llama_server.log")
        except Exception:  # pragma: no cover - defensive
            processing, prediction_tps = False, None
        emoji = "\u2699\ufe0f" if processing else "\u23f8\ufe0f"
        placeholder.markdown(
            f"**Processing:** {emoji}\n**TPS:** {prediction_tps}\n**Updated:** {time.strftime('%H:%M:%S')}"
        )
        time.sleep(1.0)


_metrics_thread: threading.Thread | None = None


def display_metrics_panel() -> None:
    """Create a sidebar placeholder and start the worker thread.

    The function must be called from inside a ``st.sidebar`` block.
    It starts the worker only once.
    """

    global _metrics_thread
    placeholder = st.sidebar.empty()
    if _metrics_thread is None:
        _metrics_thread = threading.Thread(
            target=_metrics_worker, args=(placeholder,), daemon=True
        )
        _metrics_thread.start()
