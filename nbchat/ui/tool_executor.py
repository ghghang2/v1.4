"""Single executor for all tool calls.

The legacy implementation created a new ``ThreadPoolExecutor`` for
every tool invocation.  This is wasteful and can lead to thread
leaks.  A global executor is now used, reusing the same pool.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any, Dict
import json

from nbchat.tools import TOOLS

# Create a single executor with a modest pool size.
_executor = ThreadPoolExecutor(max_workers=4)

def run_tool(tool_name: str, args_json: str, timeout: int | None = None) -> str:
    """Execute a tool with arguments and return the string result.

    Parameters
    ----------
    tool_name:
        Name of the tool to execute.
    args_json:
        JSON string containing the arguments for the tool.
    timeout:
        Optional timeout in seconds.  If ``None`` a default of 60 seconds
        is used for ``browser`` and ``run_tests`` tools, otherwise 30.
    """

    try:
        args = json.loads(args_json)
    except Exception as e:
        return f"❌ Failed to parse tool arguments: {e}"

    func = next((t.func for t in TOOLS if t.name == tool_name), None)
    if not func:
        return f"⚠️ Unknown tool '{tool_name}'"

    if timeout is None:
        timeout = 60 if tool_name in ["browser", "run_tests"] else 30

    future = _executor.submit(func, **args)
    try:
        result = future.result(timeout=timeout)
        return str(result)
    except TimeoutError:
        return f"⏰ Tool '{tool_name}' timed out after {timeout} seconds."
    except Exception as e:
        return f"❌ Tool execution error: {e}"

__all__ = ["run_tool"]