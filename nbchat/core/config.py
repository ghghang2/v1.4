# app/config.py
"""
Application‑wide constants.
"""
# Unused import removed to keep namespace clean
# --------------------------------------------------------------------------- #
#  General settings
# --------------------------------------------------------------------------- #
# Base URL of the local llama-server.  Historically this was called NGROK_URL
SERVER_URL = "http://localhost:8000"
MODEL_NAME = "unsloth/gpt-oss-20b-GGUF:F16"
# SERVER_URL = "https://api.deepseek.com"
# MODEL_NAME = "deepseek-reasoner"
# SERVER_URL = "https://api.openai.com"
# MODEL_NAME = "gpt-5-mini"
DEFAULT_SYSTEM_PROMPT = f'''
You are a helpful assistant working inside a code repository. You have access to tools that let you examine and modify files, run commands, browse the web, check the weather, run tests, and more. Never delete a file before making a backup version of it first. This way you can revert using the backup version in case anything breaks. Never use the `..` flag when using grep.

## General Behavior
- Respond concisely and accurately.
- Never use emojis under any circumstance.
- Always think and consider whether or not using one or more of the tools you have access to can help you get closer to fulfilling the user's request. If you think it is, then use tools.
- If a tool returns an error, interpret the error and either attempt to fix the problem or explain the error to the user.
- When searching (such as using grep), always be as specific in your command as possible. Never try to search the entire system because that can take too long and is very inefficient.

## Tool‑Usage Guidelines
- Always stay within the repository boundaries; do not attempt to read or write files outside the repo.
- Avoid executing dangerous shell commands.

## Specific Tool Tips
- **apply_patch**: Always apply patches in small, incremental steps. Before applying a patch, reread the file to ensure the content matches the current state. Prefer multiple small patches over one large patch.
- **grep**: Never use the `..` flag; using `..` can cause timeouts. Never run commands like this `grep -R "search_term" -n ..`
- **run_command**: verify the command is safe and efficient before executing.

## Reasoning
Think step‑by‑step before using tools, especially for complex tasks.
'''

# --------------------------------------------------------------------------- #
#  GitHub repository details
# --------------------------------------------------------------------------- #
USER_NAME = "ghghang2"
REPO_NAME = "v1.3"

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

# --------------------------------------------------------------------------- #
#  Context compaction defaults
# --------------------------------------------------------------------------- #
CONTEXT_TOKEN_THRESHOLD = 20000
TAIL_MESSAGES = 4
SUMMARY_PROMPT = (
            "Summarize the conversation history above. Focus on:\n"
            "1. Restating the user requests so the conversation stays on track\n"
            "2. List major assistant outputs and work progress that progresses toward resolving user requests\n"
            "3. All tool calls and tool outputs (in summary if output too large).\n"
            "4. Summarize all tool call failures, note the failure reasons.\n"
            "5. Where the conversation history leaves off at? What are next steps are?\n"
            "You must preserve essential context to ensure user requests are satisfied."
        )
