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

def browser(url: str, actions: Optional[List[Dict[str, Any]]] = None, selector: Optional[str] = None, **kwargs) -> str:
    """
    Visit a webpage, perform optional interactions, and extract content.
    
    This tool is STATELESS: It opens a browser, runs your commands, and closes.
    You cannot "keep" the browser open between calls.
    
    Parameters
    ----------
    url : str
        The URL to visit.
    actions : List[Dict], optional
        A list of interactions to perform before extracting data.
        Supported action types:
        - {"type": "click", "selector": "..."}
        - {"type": "type", "selector": "...", "text": "..."}
        - {"type": "wait", "selector": "..."} (or "timeout": ms)
        - {"type": "screenshot", "path": "..."}
    selector : str, optional
        A specific CSS selector to extract text from. If None, returns the full page text.
    **kwargs :
        Handles "hallucinated" nested JSON arguments from some LLMs.

    Returns
    -------
    str
        JSON string containing the extracted text, source, or operation results.
    """

    # --- 1. ARGUMENT UNPACKING (Fixes the "url is required" error) ---
    # LLMs sometimes wrap args inside a 'kwargs' string. We unpack them here.
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
            # Launch fresh for every single call
            browser = p.firefox.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
            page = context.new_page()

            # Navigate
            try:
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
            except Exception as e:
                return json.dumps({"error": f"Navigation failed: {str(e)}"})

            # Perform Actions (if any)
            interaction_log = []
            if actions:
                for act in actions:
                    act_type = act.get("type")
                    try:
                        if act_type == "click":
                            page.click(act["selector"], timeout=5000)
                            interaction_log.append(f"Clicked {act['selector']}")
                        elif act_type == "type":
                            page.fill(act["selector"], act["text"], timeout=5000)
                            interaction_log.append(f"Typed into {act['selector']}")
                        elif act_type == "wait":
                            if "selector" in act:
                                page.wait_for_selector(act["selector"], timeout=10000)
                            elif "timeout" in act:
                                page.wait_for_timeout(act["timeout"])
                            interaction_log.append(f"Waited for {act.get('selector') or act.get('timeout')}")
                        elif act_type == "screenshot":
                            path = act.get("path", "screenshot.png")
                            page.screenshot(path=path)
                            interaction_log.append(f"Screenshot saved to {path}")
                    except Exception as e:
                        interaction_log.append(f"Error during {act_type}: {str(e)}")

            # Extract Content
            content = ""
            if selector:
                try:
                    # Try to get specific element
                    page.wait_for_selector(selector, timeout=5000)
                    elements = page.locator(selector).all_inner_texts()
                    content = "\n".join(elements)
                except:
                    content = f"Element '{selector}' not found."
            else:
                # Default: Get the main readable text
                content = page.evaluate("() => document.body.innerText")

            browser.close()
            
            return json.dumps({
                "status": "success",
                "url": url,
                "interactions": interaction_log,
                "content": content[:5000]  # Truncate to avoid context limit overflow
            })

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