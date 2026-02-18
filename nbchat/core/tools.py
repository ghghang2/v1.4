"""Tool registry and execution helpers.

The legacy implementation lives in :mod:`app.tools`.  This module
provides a thin wrapper that re‑exports the public API so that the UI
and conversation logic can import from ``nbchat.core.tools`` instead of
``app.tools``.
"""

from __future__ import annotations

from typing import Callable, Dict, List

# The actual discovery logic is implemented in ``app.tools``.  We
# simply import the helpers and expose them under the new module name.
from app.tools import get_tools as _get_tools
from app.tools import TOOLS as _TOOLS

def get_tools() -> List[Dict]:
    """Return the list of OpenAI function tools.

    The function delegates to :func:`app.tools.get_tools`.
    """

    return _get_tools()


def execute_tool(name: str, args: Dict[str, Any]) -> str:
    """Execute a tool by name.

    Parameters
    ----------
    name:
        The tool name as returned by :func:`get_tools`.
    args:
        A mapping of arguments to pass to the underlying function.

    Returns
    -------
    str
        The string representation of the tool's return value.
    """

    for tool in _TOOLS:
        if tool.name == name:
            try:
                return str(tool.func(**args))
            except Exception as e:  # pragma: no cover - defensive
                return f"⚠️ Tool error: {e}"
    return f"⚠️ Unknown tool '{name}'"
