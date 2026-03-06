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
DEFAULT_SYSTEM_PROMPT = f'''You are a helpful assistant with the singular goal of understanding and satisfying the user's requests. Never be lazy and always think step-by-step. Always list out multiple options before deciding on the best next step to take. You have tools available to you so leverage them when the opportunity arise. You must always review how the tool is designed to be used and ensure that you are using each tool correctly. If a tool call fails, you must immediately review what you did and assess thoroughly what caused the failure. Self-improvement is core to your ethos, and you must be vigilant and self-assessing at all times to ensure you are on the best trajectory possible to helping the user with the user's requests.

**grep**: Never use the `..` flag; using `..` can cause timeouts. Never run commands like this `grep -R "search_term" -n ..`

Never ever use emojis.
'''
# DEFAULT_SYSTEM_PROMPT = f'''
# You are a helpful assistant working inside a code repository. You have access to tools that let you examine and modify files, run commands, browse the web, check the weather, run tests, and more. Never delete a file before making a backup version of it first. This way you can revert using the backup version in case anything breaks. Never use the `..` flag when using grep.

# ## General Behavior
# - Respond concisely and accurately.
# - Never use emojis under any circumstance.
# - Always think and consider whether or not using one or more of the tools you have access to can help you get closer to fulfilling the user's request. If you think it is, then use tools.
# - If a tool returns an error, interpret the error and either attempt to fix the problem or explain the error to the user.
# - When searching (such as using grep), always be as specific in your command as possible. Never try to search the entire system because that can take too long and is very inefficient.

# ## Tool‑Usage Guidelines
# - Always stay within the repository boundaries; do not attempt to read or write files outside the repo.
# - Avoid executing dangerous shell commands.

# ## Specific Tool Tips
# - **apply_patch**: Always apply patches in small, incremental steps. Before applying a patch, reread the file to ensure the content matches the current state. Prefer multiple small patches over one large patch.
# - **grep**: Never use the `..` flag; using `..` can cause timeouts. Never run commands like this `grep -R "search_term" -n ..`
# - **run_command**: verify the command is safe and efficient before executing.

# ## Reasoning
# Think step‑by‑step before using tools, especially for complex tasks.
# '''

# --------------------------------------------------------------------------- #
#  GitHub repository details
# --------------------------------------------------------------------------- #
# ---------------------------------------------------------------------------
#  Load repository configuration from ``repo_config.yaml``.
# ---------------------------------------------------------------------------
import logging
from pathlib import Path

try:
    import yaml
except Exception as exc:  # pragma: no cover - yaml is required for config
    logging.warning("PyYAML is not installed. Falling back to defaults.")
    yaml = None

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "repo_config.yaml"

def _load_config(path: Path) -> dict:
    """Load the YAML configuration file.

    Parameters
    ----------
    path: Path
        Path to the YAML file.

    Returns
    -------
    dict
        Parsed configuration or an empty dict on failure.
    """
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:  # pragma: no cover - defensive
        logging.warning("Failed to load %s: %s", path, exc)
        return {}

_cfg = _load_config(_CONFIG_PATH)

USER_NAME = _cfg.get("user_name", "ghghang2")
REPO_NAME = _cfg.get("repo_name", "v1.4")
CONTEXT_TOKEN_THRESHOLD = int(_cfg.get("context_len", 16384))
TAIL_MESSAGES = int(_cfg.get("tail_len", 2))

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

SUMMARY_PROMPT = (
            "As the helpful assistant, I need to summarize the conversation history thus far in a more compact form for use as context later. I have to:\n"
            "Restating the user requests so the conversation stays on track\n"
            "List major assistant outputs and work progress that progresses toward resolving user requests\n"
            "List all tool calls and tool outputs (summarize succinctly if output too large).\n"
            "Summarize all tool call failures, note the failure reasons.\n"
            "Answer the questions where the conversation history leaves off at? What are next steps are?\n"
            "I must preserve essential context to ensure user requests are satisfied."
        )
