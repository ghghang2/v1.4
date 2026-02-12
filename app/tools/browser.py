"""Stateless Chromium Browser Tool with Automation Evasion."""

from __future__ import annotations
import json
from typing import Any, List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor
from playwright.sync_api import sync_playwright

def browser(url: str, actions: Optional[List[Dict[str, Any]]] = None, selector: Optional[str] = None, **kwargs) -> str:
    # --- 1. ARGUMENT UNPACKING ---
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

    def run_chromium_stealth(target_url, target_actions, target_selector):
        try:
            with sync_playwright() as p:
                # 1. Chromium-specific "Stealth" flags
                # '--disable-blink-features=AutomationControlled' is the key to hiding webdriver
                browser_instance = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
                    ]
                )
                
                context = browser_instance.new_context(
                    viewport={'width': 1920, 'height': 1080}
                )

                # 2. JavaScript injection to clean up any remaining bot-traces
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                """)

                page = context.new_page()

                try:
                    # News sites like The Hill often load better with 'networkidle'
                    # which waits for all the tracking scripts to settle.
                    page.goto(target_url, timeout=45000, wait_until="networkidle")
                except Exception as e:
                    browser_instance.close()
                    return json.dumps({"error": f"Navigation failed: {str(e)}"})

                # --- 3. DETECTION CHECK & EXTRACTION ---
                page_content = page.evaluate("() => document.body.innerText")
                
                # If we still hit the "Press & Hold", try one human-like scroll
                if "Press & Hold" in page_content or "confirm you are a human" in page_content:
                    page.mouse.wheel(0, 400)
                    page.wait_for_timeout(2000)
                    page_content = page.evaluate("() => document.body.innerText")

                # Extraction Logic
                content = ""
                if target_selector:
                    try:
                        page.wait_for_selector(target_selector, timeout=5000)
                        content = "\n".join(page.locator(target_selector).all_inner_texts())
                    except:
                        content = f"Selector '{target_selector}' not found."
                else:
                    # Clean up the body text to remove script tags
                    content = page.evaluate("() => document.body.innerText")

                browser_instance.close()
                return json.dumps({
                    "status": "success",
                    "url": target_url,
                    "content": content[:5000].strip()
                })
        except Exception as e:
            return json.dumps({"error": f"Internal Error: {str(e)}"})

    # --- 4. RUN IN THREAD ---
    with ThreadPoolExecutor() as executor:
        return executor.submit(run_chromium_stealth, url, actions, selector).result()

# ---------------------------------------------------------------------------
# Tool Definition
# ---------------------------------------------------------------------------
func = browser
name = "browser"
description = """
Browser tool. Use this to visit a website and extract content.
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