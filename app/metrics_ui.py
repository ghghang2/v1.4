"""Streamlit UI for displaying Llama metrics.

The original implementation used an infinite `while True` loop which blocks
Streamlit's execution, preventing the app from rendering.  The updated
version performs a single fetch and displays the data.  For real‑time
updates users can call :func:`display_metrics_panel` again or use a
Streamlit timer.
"""

import streamlit as st
import requests
import time

# Cache the metrics for 3 seconds to avoid excessive HTTP requests.
# @st.cache_data(ttl=3)
def get_llama_metrics(url: str) -> dict[str, str]:
    """Fetch metrics from the Llama server.

    Parameters
    ----------
    url: str
        The URL to query for metrics.

    Returns
    -------
    dict[str, str]
        Mapping of metric name to value.
    """
    try:
        resp = requests.get(url, timeout=2)
        resp.raise_for_status()
    except Exception as exc:  # pragma: no cover - defensive
        st.error(f"Could not fetch metrics: {exc}")
        return {}

    metrics: dict[str, str] = {}
    for line in resp.text.splitlines():
        if line.startswith("#") or not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            metrics[parts[0]] = parts[1]
    return metrics

@st.fragment(run_every=1.0)
def display_metrics_panel() -> None:
    """Display a sidebar panel with the latest metrics.

    The function fetches metrics once and renders them.  It does not
    block the UI, making it safe to call from a Streamlit app.
    """
    # placeholder = st.sidebar.empty()
    base_url = "http://localhost:8000/metrics"
    metrics = get_llama_metrics(base_url)

    if metrics:
        for k, v in metrics.items():
            st.metric(label=k, value=v)
        st.write(f"Updated: {time.strftime('%H:%M:%S')}")
    else:
        placeholder.info("No metrics returned from server.")
