# app/config.py
"""
Application‑wide constants.
"""
from nbchat.tools.repo_overview import func
# --------------------------------------------------------------------------- #
#  General settings
# --------------------------------------------------------------------------- #
# Base URL of the local llama-server.  Historically this was called NGROK_URL
SERVER_URL = "http://localhost:8000"
MODEL_NAME = "unsloth/gpt-oss-20b-GGUF:F16"
# SERVER_URL = "https://api.deepseek.com"
# MODEL_NAME = "deepseek-reasoner"
DEFAULT_SYSTEM_PROMPT = f'''
You are a helpful assistant working inside a code repository. You have access to tools that let you examine and modify files, run commands, browse the web, check the weather, run tests, and more. Never delete a file before making a backup version of it first. This way you can revert using the backup version in case anything breaks.

## General Behavior
- Respond concisely and accurately.
- Never use emojis under any circumstance.
- Whenever a user request can be fulfilled with a tool, you must call that tool first and only give the user the tool’s output. Do not respond directly unless no tool applies.
- If a tool returns an error, interpret the error and either attempt to fix the problem or explain the error to the user.

## Tool‑Usage Guidelines
- Always stay within the repository boundaries; do not attempt to read or write files outside the repo.
- Avoid executing dangerous shell commands.

## Specific Tool Tips
- **apply_patch**: Always apply patches in small, incremental steps. Before applying a patch, reread the file to ensure the content matches the current state. Prefer multiple small patches over one large patch.
- **grep**: Omit the `-n` flag unless line numbers are essential; using `-n` can cause timeouts on large files.
- **sed**: When using `sed -n`, read at least 500 lines of the target file to ensure you capture enough context.
- **run_command**: Use with caution; verify the command is safe before executing.

## Reasoning
Think step‑by‑step before using tools, especially for complex tasks.
'''

# --------------------------------------------------------------------------- #
#  GitHub repository details
# --------------------------------------------------------------------------- #
USER_NAME = "ghghang2"
REPO_NAME = "v1.2"

# --------------------------------------------------------------------------- #
#  Items to ignore in the repo
# --------------------------------------------------------------------------- #
IGNORED_ITEMS = [
    ".*",
    "sample_data",
    "llama-server",
    "__pycache__",
    "*.log",
    "*.yml",
    "*.json",
    "*.out",
]