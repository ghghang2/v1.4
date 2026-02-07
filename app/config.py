# app/config.py
"""
Application‑wide constants.
"""
from app.tools.repo_overview import func
# --------------------------------------------------------------------------- #
#  General settings
# --------------------------------------------------------------------------- #
NGROK_URL = "http://localhost:8000"

MODEL_NAME = "unsloth/gpt-oss-20b-GGUF:F16"
DEFAULT_SYSTEM_PROMPT = f'''
Respond concisely and accurately.
Use the provided tools to satisfy user requests.
• When running grep, omit the -n flag to avoid timeouts.
• When using sed -n, read at least 500 lines of the target file.
'''

# --------------------------------------------------------------------------- #
#  GitHub repository details
# --------------------------------------------------------------------------- #
USER_NAME = "ghghang2"
REPO_NAME = "v1.1"

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