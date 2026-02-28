"""Stateless Browser Tool for OpenAI Function Calling.

This module provides a robust, stateless wrapper around Playwright.
Each call launches a fresh browser instance, performs a sequence of actions,
returns the result, and cleans up immediately. This prevents threading
crashes and "protocol" errors common in long-running sessions.
"""

from __future__ import annotations

import json
from typing import Any, List, Dict, Optional
from playwright.sync_api import sync_playwright

def browser(
    url: str,
    actions: Optional[List[Dict[str, Any]]] = None,
    selector: Optional[str] = None,
    navigation_timeout: int = 30000,
    action_timeout: int = 5000,
    max_content_length: int = 5000,
    screenshot_path: Optional[str] = None,
    **kwargs,
) -> str:
    """Stateless browser wrapper using Playwright.

    The function launches a fresh browser instance for each call, performs any
    optional actions, extracts page content, and then tears the browser down.
    This design avoids shared state and makes the tool safe for concurrent use.

    Parameters
    ----------
    url: str
        The URL to visit.
    actions: list[dict], optional
        A list of user interactions. Each dict must contain a ``type`` key
        and any additional keys required for that action:

        ``click``   – ``selector`` required.
        ``type``    – ``selector`` and ``text`` required.
        ``wait``    – either ``selector`` or ``timeout`` (ms) required.
        ``screenshot`` – optional ``path``; defaults to ``"screenshot.png"``.
    selector: str, optional
        CSS selector from which to extract text. If omitted, the entire page
        body text is returned.
    navigation_timeout: int, optional
        Timeout in milliseconds for page navigation.
    action_timeout: int, optional
        Default timeout for click, type, and wait actions.
    max_content_length: int, optional
        Maximum number of characters returned in ``content``.
    screenshot_path: str, optional
        Path to store the screenshot. If ``None`` the action's ``path`` key
        is used or a default ``screenshot.png``.
    **kwargs
        Accepts a nested JSON string under the ``kwargs`` key for LLM
        compatibility.

    Returns
    -------
    str
        JSON string containing the extracted text, source, or operation
        results. On failure an ``{"error": ...}`` payload is returned.
    """

    # --- 1. ARGUMENT UNPACKING (Fixes the "url is required" error) ---
    # LLMs sometimes wrap args inside a 'kwargs' string. We unpack them here.
    # --- 1. ARGUMENT UNPACKING (Fixes the "url is required" error) ---
    if kwargs.get("kwargs") and isinstance(kwargs["kwargs"], str):
        try:
            extra_args = json.loads(kwargs["kwargs"])
            if isinstance(extra_args, dict):
                if not url: url = extra_args.get("url")
                if not actions: actions = extra_args.get("actions")
                if not selector: selector = extra_args.get("selector")
        except json.JSONDecodeError:
            pass

    if not url:
        return json.dumps({"error": "URL is required."})

    # --- 2. STATELESS EXECUTION (Fixes the "thread" error) ---
    try:
        with sync_playwright() as p:
            # Launch fresh for every single call – Firefox is chosen for
            # stability in headless mode.
            browser = p.firefox.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
            page = context.new_page()

            # Navigate
            try:
                page.goto(url, timeout=navigation_timeout, wait_until="domcontentloaded")
            except Exception as e:
                return json.dumps({"error": f"Navigation failed: {str(e)}"})

            # Perform Actions (if any)
            interaction_log: List[str] = []
            if actions:
                for act in actions:
                    act_type = act.get("type")
                    try:
                        if act_type == "click":
                            if "selector" not in act:
                                raise ValueError("'selector' missing for click action")
                            page.click(act["selector"], timeout=action_timeout)
                            interaction_log.append(f"Clicked {act['selector']}")
                        elif act_type == "type":
                            if "selector" not in act or "text" not in act:
                                raise ValueError("'selector' or 'text' missing for type action")
                            page.fill(act["selector"], act["text"], timeout=action_timeout)
                            interaction_log.append(f"Typed into {act['selector']}")
                        elif act_type == "wait":
                            if "selector" in act:
                                page.wait_for_selector(act["selector"], timeout=action_timeout)
                            elif "timeout" in act:
                                page.wait_for_timeout(act["timeout"])
                            else:
                                raise ValueError("'selector' or 'timeout' required for wait action")
                            interaction_log.append(f"Waited for {act.get('selector') or act.get('timeout')}")
                        elif act_type == "screenshot":
                            path = act.get("path", screenshot_path or "screenshot.png")
                            page.screenshot(path=path)
                            interaction_log.append(f"Screenshot saved to {path}")
                        else:
                            interaction_log.append(f"Unknown action type: {act_type}")
                    except Exception as e:
                        interaction_log.append(f"Error during {act_type}: {str(e)}")

            # Extract Content
            # --- 3. Extract Content ---
            content: str
            if selector:
                try:
                    page.wait_for_selector(selector, timeout=action_timeout)
                    elements = page.locator(selector).all_inner_texts()
                    content = "\n".join(elements)
                except Exception:
                    content = f"Element '{selector}' not found."
            else:
                content = page.evaluate("() => document.body.innerText")

            # Clean up: close context first to release resources.
            context.close()
            browser.close()
            
            return json.dumps(
                {
                    "status": "success",
                    "url": url,
                    "interactions": interaction_log,
                    "content": content[:max_content_length],
                }
            )

    except Exception as global_ex:
        return json.dumps({"error": f"Browser tool error: {str(global_ex)}"})

# ---------------------------------------------------------------------------
# Tool Definition
# ---------------------------------------------------------------------------
func = browser
name = "browser"
description = """
Safe, stateless browser tool. Use this to visit a website and extract content.
This tool CANNOT maintain a session. Every call is a fresh visit.

Inputs:
- url (required): The website to visit.
- selector (optional): A CSS selector to extract specific text. If omitted, returns full page text.
- actions (optional): A list of actions to perform BEFORE extraction. Use this to click buttons or log in.
  Example actions: 
  [
    {"type": "click", "selector": "#cookie-accept"}, 
    {"type": "type", "selector": "#search", "text": "AI News"},
    {"type": "wait", "selector": "#results"}
  ]
"""

__all__ = ["browser", "func", "name", "description"]