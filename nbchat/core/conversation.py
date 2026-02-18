"""Conversation processing logic.

The original implementation lived inside :mod:`nbchat_v2`.  This
module contains a lightweight placeholder that exposes the public API
expected by the UI.  The full logic is still being migrated and is
replaced with no‑op stubs.
"""

from __future__ import annotations

from typing import Any, List, Tuple


def process_turn(messages: List[Tuple[str, str]], tools: Any, client: Any) -> Tuple[str, str, List[Any], str]:
    """Process a single turn.

    Parameters
    ----------
    messages:
        List of ``(role, content)`` tuples.
    tools:
        The list of OpenAI tool definitions.
    client:
        The LLM client.

    Returns
    -------
    reasoning, content, tool_calls, finish_reason
        The result of the LLM call.
    """

    # Placeholder – return empty values.  The real implementation will
    # stream from the LLM and parse the response.
    return "", "", [], ""  # pragma: no cover
