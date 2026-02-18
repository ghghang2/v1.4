"""Client wrapper for the Llama OpenAI API.

This module simply re‑exports :func:`app.client.get_client` under the
``nbchat.core`` namespace.
"""

from __future__ import annotations

from typing import Any

from app.client import get_client as _get_client

def get_client() -> Any:
    """Return an instance of :class:`openai.OpenAI` configured for Llama."""
    return _get_client()
