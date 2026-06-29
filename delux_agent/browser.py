from __future__ import annotations

import os
import platform
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BrowserResult:
    ok: bool
    output: str


def _is_termux() -> bool:
    return bool(os.environ.get("PREFIX")) and os.path.exists(
        os.path.join(os.environ["PREFIX"], "bin")
    )


def _detect_platform() -> str:
    if _is_termux():
        return "android"
    return platform.system().lower()


def _find_chromium() -> str | None:
    candidates = []
    prefix = os.environ.get("PREFIX", "")
    if prefix:
        candidates.append(os.path.join(prefix, "bin", "chromium"))
        candidates.append(os.path.join(prefix, "bin", "chromium-browser"))
        candidates.append(os.path.join(prefix, "bin", "chromium-browser-stable"))
    candidates.extend([
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/snap/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ])
    env_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if env_path:
        candidates.insert(0, env_path)
    for path in candidates:
        if path and os.path.exists(path) and os.access(path, os.X_OK):
            return path


def _get_launch_args() -> list[str]:
    args = ["--no-sandbox"]
    plat = _detect_platform()
    if plat == "android":
        args.extend(["--disable-dev-shm-usage", "--disable-setuid-sandbox", "--disable-gpu"])
    elif plat == "linux":
        args.extend(["--disable-dev-shm-usage", "--disable-setuid-sandbox"])
    return args


class BrowserEngine:
    """Stateful browser engine for MULTI-STEP interactive web sessions.

    Browser stays OPEN between actions (navigate → click → type → snapshot).
    Use this when you need to interact across multiple pages.

    For single stateless operations, use the delux-browser skill instead:
      <action>run_skill</action>
      <skill>delux-browser</skill>
      <args>text https://url</args>
      <timeout>60</timeout>
    """
    def __init__(self, screenshot_dir: str | None = None, headless: bool = True):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._screenshot_dir = screenshot_dir or "/tmp/delux-browser"
        self._current_url = ""
        self._browser_type = "chromium"
        self._headless = headless
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

    def _launch_browser(self):
        chrome_path = _find_chromium()
        launch_kwargs = {
            "headless": self._headless,
            "args": _get_launch_args(),
        }
        if chrome_path:
            launch_kwargs["executable_path"] = chrome_path

        self._browser_type = "chromium"
        for browser_name in ("chromium", "firefox"):
            if browser_name == "chromium":
                launcher = self._pw.chromium
            else:
                launcher = self._pw.firefox
            try:
                if browser_name == "firefox":
                    self._browser = launcher.launch(
                        headless=self._headless,
                        args=["--no-sandbox"] if _detect_platform() in ("android", "linux") else [],
                    )
                else:
                    self._browser = launcher.launch(**launch_kwargs)
                self._browser_type = browser_name
                return
            except Exception:
                continue
        raise RuntimeError(
            "No working browser found (tried chromium, firefox). "
            "Run: pip install playwright && python -m playwright install chromium"
        )

    def start(self):
        self._ensure_playwright()
        if self._browser is None:
            self._launch_browser()
            if self._context is None:
                self._context = self._browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                self._page = self._context.new_page()

    def stop(self):
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                self._playwright.__exit__(None, None, None)
            except Exception:
                pass
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
            self._page.wait_for_selector(selector, timeout=5000)
            self._page.click(selector, timeout=5000)
            time.sleep(0.5)
            return BrowserResult(True, self._snapshot())
        except Exception as e:
            return BrowserResult(False, f"Click failed on '{selector}': {str(e)[:200]}")

    def type(self, selector: str, text: str) -> BrowserResult:
        if not self._page:
            return BrowserResult(False, "No page open.")
        try:
            self._page.wait_for_selector(selector, timeout=5000)
            try:
                self._page.fill(selector, text, timeout=5000)
                return BrowserResult(True, f"Typed '{text[:50]}' into {selector}")
            except Exception:
                escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
                self._page.evaluate(
                    f"(sel) => {{ const el = document.querySelector(sel); if(el) {{ el.value = '{escaped}'; el.dispatchEvent(new Event('input', {{ bubbles: true }})); el.dispatchEvent(new Event('change', {{ bubbles: true }})); }} }}",
                    selector,
                )
                return BrowserResult(True, f"Typed '{text[:50]}' into {selector} (JS fallback)")
        except Exception as e:
            err = str(e)[:200]
            return BrowserResult(False, f"Type failed on '{selector}': {err}")

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
_global_headless: bool = True


def set_headless_mode(headless: bool) -> None:
    """Set headless mode globally. Affects new browser instances."""
    global _global_headless
    _global_headless = headless


def get_browser(headless: bool | None = None, *, headed: bool = False) -> BrowserEngine:
    """Get or create the singleton browser engine.
    If `headed=True` is passed and current engine is headless, recreate it."""
    global _engine, _global_headless
    if headless is None:
        headless = not headed if headed else _global_headless
    if _engine is None:
        _engine = BrowserEngine(headless=headless)
    elif _engine._headless != headless:
        _engine.stop()
        _engine = BrowserEngine(headless=headless)
    return _engine


def close_browser():
    global _engine
    if _engine:
        _engine.stop()
        _engine = None
