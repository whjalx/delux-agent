from __future__ import annotations

import base64
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BrowserResult:
    ok: bool
    output: str


class BrowserEngine:
    """Stateful browser engine for MULTI-STEP interactive web sessions.
    
    Browser stays OPEN between actions (navigate → click → type → snapshot).
    Use this when you need to interact across multiple pages.
    
    For single stateless operations, use the delux-browser skill instead:
      {"action":"run_skill","skill":"delux-browser","args":"text https://url"}
    """
    def __init__(self, screenshot_dir: str | None = None):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._screenshot_dir = screenshot_dir or "/tmp/delux-browser"
        self._current_url = ""
        Path(self._screenshot_dir).mkdir(parents=True, exist_ok=True)

    def _ensure_playwright(self):
        if self._playwright is None:
            try:
                from playwright.sync_api import sync_playwright
                self._playwright = sync_playwright()
                self._pw = self._playwright.start()
            except ImportError:
                raise RuntimeError(
                    "Playwright not installed. Run: pip install playwright && python -m playwright install chromium"
                )

    def start(self):
        self._ensure_playwright()
        if self._browser is None:
            self._browser = self._pw.chromium.launch(headless=True)
            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            self._page = self._context.new_page()

    def stop(self):
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.__exit__(None, None, None)
            self._playwright = None
        self._page = None
        self._context = None

    def navigate(self, url: str, timeout: int = 30) -> BrowserResult:
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        try:
            self.start()
            self._page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            self._current_url = self._page.url
            return BrowserResult(True, self._snapshot())
        except Exception as e:
            return BrowserResult(False, f"Navigation failed: {e}")

    def snapshot(self) -> BrowserResult:
        if not self._page:
            return BrowserResult(False, "No page open. Use navigate first.")
        try:
            return BrowserResult(True, self._snapshot())
        except Exception as e:
            return BrowserResult(False, f"Snapshot failed: {e}")

    def _snapshot(self) -> str:
        lines = [f"URL: {self._page.url}", f"Title: {self._page.title()}"]
        body = self._page.evaluate("() => document.body?.innerText || ''") or ""
        text = body.strip()[:8000]
        if text:
            lines.append("")
            lines.append(text)
        return "\n".join(lines)

    def click(self, selector: str) -> BrowserResult:
        if not self._page:
            return BrowserResult(False, "No page open.")
        try:
            self._page.click(selector, timeout=5000)
            time.sleep(0.5)
            return BrowserResult(True, self._snapshot())
        except Exception as e:
            return BrowserResult(False, f"Click failed on '{selector}': {e}")

    def type(self, selector: str, text: str) -> BrowserResult:
        if not self._page:
            return BrowserResult(False, "No page open.")
        try:
            self._page.fill(selector, text, timeout=5000)
            return BrowserResult(True, f"Typed '{text[:100]}' into {selector}")
        except Exception as e:
            return BrowserResult(False, f"Type failed: {e}")

    def scroll(self, direction: str = "down", amount: int = 500) -> BrowserResult:
        if not self._page:
            return BrowserResult(False, "No page open.")
        delta = amount if direction == "down" else -amount
        try:
            self._page.evaluate(f"window.scrollBy(0, {delta})")
            time.sleep(0.3)
            return BrowserResult(True, self._snapshot())
        except Exception as e:
            return BrowserResult(False, f"Scroll failed: {e}")

    def back(self) -> BrowserResult:
        if not self._page:
            return BrowserResult(False, "No page open.")
        try:
            self._page.go_back()
            self._current_url = self._page.url
            return BrowserResult(True, self._snapshot())
        except Exception as e:
            return BrowserResult(False, f"Back failed: {e}")

    def screenshot(self, full_page: bool = False) -> BrowserResult:
        if not self._page:
            return BrowserResult(False, "No page open.")
        try:
            ts = int(time.time())
            path = os.path.join(self._screenshot_dir, f"screenshot_{ts}.png")
            self._page.screenshot(path=path, full_page=full_page)
            return BrowserResult(True, f"Screenshot saved to {path}")
        except Exception as e:
            return BrowserResult(False, f"Screenshot failed: {e}")

    def extract_text(self) -> BrowserResult:
        if not self._page:
            return BrowserResult(False, "No page open.")
        try:
            text = self._page.evaluate("() => document.body?.innerText || 'No text found'") or ""
            return BrowserResult(True, text.strip()[:15000])
        except Exception as e:
            return BrowserResult(False, f"Extract failed: {e}")


_engine: BrowserEngine | None = None


def get_browser() -> BrowserEngine:
    global _engine
    if _engine is None:
        _engine = BrowserEngine()
    return _engine


def close_browser():
    global _engine
    if _engine:
        _engine.stop()
        _engine = None
