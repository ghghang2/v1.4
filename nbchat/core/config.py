"""Default system prompt and model name.

The values are taken from :mod:`app.config`.  They are re‑exported
so that the UI and core logic can import from ``nbchat.core.config``.
"""

from __future__ import annotations

from app.config import DEFAULT_SYSTEM_PROMPT, MODEL_NAME
