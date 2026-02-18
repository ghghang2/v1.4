"""Utility helpers shared across the nbchat package.

Only a handful of functions from the legacy code are required for the
new modular structure.  They are copied verbatim to avoid having the
legacy module depend on the new one.
"""

import markdown


def md_to_html(text: str) -> str:
    """Convert markdown to HTML using fenced code blocks.

    This is the same implementation that lived in the legacy file.
    """
    # Enable the tables extension so markdown tables render correctly.
    return markdown.markdown(text, extensions=["fenced_code", "codehilite", "tables"])


# Lazy import helper – copied from nbchat_v2.
_client = None
_tools = None
_db_module = None
_config_module = None


def lazy_import(module_name: str):
    """Import a module only when needed.

    The function mirrors the behaviour of the legacy ``lazy_import``.
    """
    global _client, _tools, _db_module, _config_module
    if module_name == "nbchat.core.client":
        if _client is None:
            from nbchat.core.client import get_client
            _client = get_client
        return _client()
    elif module_name == "nbchat.tools":
        if _tools is None:
            from nbchat.tools import get_tools
            _tools = get_tools
        return _tools()
    elif module_name == "nbchat.core.db":
        if _db_module is None:
            import nbchat.core.db as db_module
            _db_module = db_module
        return _db_module
    elif module_name == "nbchat.core.config":
        if _config_module is None:
            import nbchat.core.config as config_module
            _config_module = config_module
        return _config_module
    else:
        raise ValueError(f"Unknown module {module_name}")