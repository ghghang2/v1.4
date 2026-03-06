"""Tool output compressor.

Compresses individual tool outputs via a quick LLM call before they are
stored in messages sent to the model.  This keeps token usage bounded
during long agentic loops without losing critical information.
"""
from __future__ import annotations

import logging
from typing import Optional

_log = logging.getLogger("nbchat.compaction")
if not _log.handlers:
    _h = logging.FileHandler("compaction.log", mode="a")
    _h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.DEBUG)

# Tool outputs shorter than this pass through verbatim — no LLM call.
# Set high enough that most file reads are preserved intact.
COMPRESS_THRESHOLD_CHARS = 8000

# These tools always produce content worth keeping verbatim.
# Never run relevance filtering on them — just truncate if huge.
ALWAYS_KEEP_TOOLS = {
    "read_file", "cat", "grep", "find", "ls", "tree", "glob",
    "list_files", "list_directory", "view_file", "get_file",
    "bash", "run_command", "execute", "sed", "awk", "head", "tail",
}


def compress_tool_output(
    tool_name: str,
    tool_args: str,
    result: str,
    model: str,
    client,
) -> str:
    """Return a compressed version of *result*.

    Strategy:
    1. Short outputs (< COMPRESS_THRESHOLD_CHARS) pass through unchanged.
    2. File-read and command tools use head+tail truncation — no LLM call,
       no information loss through relevance filtering.
    3. All other tools use an LLM call that preserves structure (signatures,
       errors, paths, values) rather than filtering by relevance.
    """
    if len(result) <= COMPRESS_THRESHOLD_CHARS:
        return result

    _log.debug(
        f"compress: {tool_name} output is {len(result)} chars"
    )

    # For file/command tools, preserve head+tail verbatim.
    # Relevance filtering causes the model to re-read files repeatedly
    # because the summary is too thin to act on.
    if tool_name in ALWAYS_KEEP_TOOLS:
        half = COMPRESS_THRESHOLD_CHARS // 2
        compressed = (
            result[:half]
            + f"\n[...{len(result) - COMPRESS_THRESHOLD_CHARS} chars omitted"
            f" (middle of output)...]\n"
            + result[-half:]
        )
        _log.debug(
            f"compress: {tool_name} truncated {len(result)} -> {len(compressed)} chars"
        )
        return compressed

    # For other tools (search results, API responses, etc.) use LLM
    # compression that preserves structure rather than filtering relevance.
    max_raw = 12_000
    truncated_input = result[:max_raw] + (
        f"\n[...{len(result) - max_raw} chars truncated for compression...]"
        if len(result) > max_raw else ""
    )

    prompt = (
        f"Tool called: {tool_name}\n"
        f"Arguments: {tool_args}\n"
        f"Output:\n{truncated_input}\n\n"
        "Summarise this output concisely. Preserve:\n"
        "- All function/class/method signatures and names\n"
        "- Error messages and stack traces verbatim\n"
        "- File paths and line numbers\n"
        "- Any values explicitly returned or printed\n"
        "Omit only: blank lines, boilerplate comments, and large repeated blocks.\n"
        "If the output is empty or a bare confirmation (e.g. 'OK', 'None', ''), "
        "respond with exactly: NO_RELEVANT_OUTPUT\n"
        "Write only the summary, no preamble."
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
        )
        compressed = response.choices[0].message.content.strip()
        _log.debug(
            f"compress: {tool_name} LLM compressed "
            f"{len(result)} -> {len(compressed)} chars"
        )
        return compressed
    except Exception as e:
        _log.debug(f"compress: LLM call failed ({e}), falling back to truncation")
        half = COMPRESS_THRESHOLD_CHARS // 2
        return (
            result[:half]
            + f"\n[...{len(result) - COMPRESS_THRESHOLD_CHARS} chars omitted...]\n"
            + result[-half:]
        )


__all__ = ["compress_tool_output", "COMPRESS_THRESHOLD_CHARS", "ALWAYS_KEEP_TOOLS"]