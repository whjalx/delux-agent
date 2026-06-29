#!/usr/bin/env python3
"""Playwright browser automation — production-grade CLI with JSON output."""

import json
import os
import re
import sys
import tempfile
import time
import traceback
from urllib.parse import urlparse

MAX_HTML_SIZE = 500000
MAX_TEXT_SIZE = 200000
MAX_LINKS = 500
MAX_TABLE_ROWS = 1000
NAV_RETRIES = 3
NAV_RETRY_DELAY = 1.5
DEFAULT_TIMEOUT = 15000
DEFAULT_NAV_TIMEOUT = 20000
DEFAULT_VIEWPORT = {"width": 1280, "height": 720}
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

VALID_ACTIONS = {
    "screenshot", "html", "text", "click", "fill",
    "links", "table", "evaluate", "pdf",
}


def _validate_url(url: str) -> str:
    """Validate and sanitize a URL. Returns normalized URL or raises ValueError."""
    if not url or not isinstance(url, str):
        raise ValueError("URL is required and must be a non-empty string")
    url = url.strip()
    if not url:
        raise ValueError("URL is required and must be a non-empty string")
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
    if not parsed.netloc:
        raise ValueError(f"Invalid URL: no hostname found in '{url}'")
    return url


def _validate_selector(selector: str, label: str = "CSS selector") -> str:
    """Validate a CSS selector string."""
    if not selector or not isinstance(selector, str):
        raise ValueError(f"{label} is required and must be a non-empty string")
    selector = selector.strip()
    if not selector:
        raise ValueError(f"{label} is required and must be a non-empty string")
    if len(selector) > 1000:
        raise ValueError(f"{label} is too long (max 1000 characters)")
    return selector


def _validate_action(action: str) -> str:
    """Validate the action parameter."""
    if not action or not isinstance(action, str):
        raise ValueError("Action is required")
    action = action.strip().lower()
    if action not in VALID_ACTIONS:
        raise ValueError(f"Unknown action: '{action}'. Valid: {', '.join(sorted(VALID_ACTIONS))}")
    return action


def _validate_viewport(raw: str | None) -> dict | None:
    """Parse and validate viewport string like '1280x720'."""
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        return None
    m = re.match(r"^(\d{2,5})[xX](\d{2,5})$", raw.strip())
    if not m:
        raise ValueError(f"Invalid viewport format: '{raw}'. Use WIDTHxHEIGHT (e.g., 1280x720)")
    w, h = int(m.group(1)), int(m.group(2))
    if w < 320 or w > 5120 or h < 240 or h > 4320:
        raise ValueError(f"Viewport dimensions out of range (320-5120 x 240-4320): {w}x{h}")
    return {"width": w, "height": h}


def _validate_timeout(raw: str | None) -> int:
    """Parse and validate timeout in milliseconds."""
    if raw is None:
        return DEFAULT_TIMEOUT
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid timeout value: '{raw}'. Must be an integer (milliseconds)")
    if val < 1000 or val > 120000:
        raise ValueError(f"Timeout must be between 1000 and 120000 ms, got {val}")
    return val


def _browser_action(
    action: str,
    url: str,
    *args: str,
    viewport: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Execute a single browser action. Returns result dict."""
    result: dict = {"action": action, "url": url, "status": "ok"}
    viewport = viewport or DEFAULT_VIEWPORT

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "status": "error",
            "error": (
                "Playwright is not installed. "
                "Install with: pip install playwright && python3 -m playwright install chromium"
            ),
        }

    browser = None
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-setuid-sandbox",
                        "--disable-gpu",
                    ],
                )
            except Exception as e:
                msg = str(e)[:300]
                return {
                    "status": "error",
                    "error": (
                        f"Failed to launch Chromium: {msg}. "
                        "Install browsers with: python3 -m playwright install chromium"
                    ),
                }

            context = browser.new_context(
                viewport=viewport,
                user_agent=USER_AGENT,
                bypass_csp=True,
            )
            page = context.new_page()
            page.set_default_timeout(timeout)

            last_error = None
            for attempt in range(1, NAV_RETRIES + 1):
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_NAV_TIMEOUT)
                    last_error = None
                    break
                except Exception as e:
                    last_error = str(e)[:500]
                    if attempt < NAV_RETRIES:
                        time.sleep(NAV_RETRY_DELAY)
                        continue

            if last_error is not None:
                return {
                    "status": "error",
                    "error": f"Failed to navigate to {url} after {NAV_RETRIES} attempts: {last_error}",
                }

            if action == "screenshot":
                selector = args[0] if args else None
                suffix = os.urandom(4).hex()
                tmp = os.path.join(tempfile.gettempdir(), f"delux_screenshot_{suffix}.png")
                try:
                    if selector:
                        selector = _validate_selector(selector)
                        el = page.wait_for_selector(selector, timeout=timeout)
                        if el is None:
                            return {
                                "status": "error",
                                "error": f"Selector not found on page: {selector}",
                            }
                        el.screenshot(path=tmp)
                    else:
                        page.screenshot(path=tmp, full_page=True)
                    if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
                        return {"status": "error", "error": "Screenshot file is empty or was not created"}
                    result["file"] = tmp
                    result["preview"] = f"Screenshot saved: {tmp}"
                except PermissionError:
                    return {"status": "error", "error": f"Permission denied writing screenshot to {tmp}"}
                except OSError as e:
                    return {"status": "error", "error": f"Failed to save screenshot: {str(e)[:300]}"}

            elif action == "html":
                try:
                    html = page.content()
                except Exception as e:
                    return {"status": "error", "error": f"Failed to get page HTML: {str(e)[:300]}"}
                if html and len(html) > MAX_HTML_SIZE:
                    result["truncated"] = True
                    result["original_size"] = len(html)
                    html = html[:MAX_HTML_SIZE]
                result["html"] = html if html else ""

            elif action == "text":
                try:
                    if args:
                        selector = _validate_selector(args[0])
                        page.wait_for_selector(selector, timeout=timeout)
                        els = page.locator(selector).all()
                        text = "\n".join(e.inner_text() for e in els)
                    else:
                        text = page.locator("body").inner_text()
                except Exception as e:
                    return {"status": "error", "error": f"Failed to extract text: {str(e)[:300]}"}
                if text and len(text) > MAX_TEXT_SIZE:
                    result["truncated"] = True
                    result["original_size"] = len(text)
                    text = text[:MAX_TEXT_SIZE]
                result["text"] = text if text else ""

            elif action == "click":
                if not args:
                    return {"status": "error", "error": "click requires a CSS selector argument"}
                selector = _validate_selector(args[0])
                try:
                    page.wait_for_selector(selector, timeout=timeout)
                    page.click(selector)
                    page.wait_for_timeout(1000)
                except Exception as e:
                    return {"status": "error", "error": f"Failed to click '{selector}': {str(e)[:300]}"}
                try:
                    result["html"] = page.content()
                    result["text"] = page.locator("body").inner_text()
                except Exception as e:
                    return {"status": "error", "error": f"Clicked but failed to read page: {str(e)[:300]}"}

            elif action == "fill":
                if len(args) < 2:
                    return {"status": "error", "error": "fill requires a CSS selector and text value"}
                selector = _validate_selector(args[0])
                value = args[1] if args[1] else ""
                if len(value) > 10000:
                    return {"status": "error", "error": "fill text value too long (max 10000 characters)"}
                try:
                    page.wait_for_selector(selector, timeout=timeout)
                    page.fill(selector, value)
                except Exception as e:
                    return {"status": "error", "error": f"Failed to fill '{selector}': {str(e)[:300]}"}
                result["filled_selector"] = selector
                result["filled_preview"] = value[:50]

            elif action == "links":
                selector = args[0] if args else "a[href]"
                try:
                    _validate_selector(selector)
                except ValueError:
                    selector = "a[href]"
                try:
                    els = page.locator(selector).all()
                except Exception as e:
                    return {"status": "error", "error": f"Failed to query links: {str(e)[:300]}"}
                links = []
                for e in els[:MAX_LINKS]:
                    try:
                        href = e.get_attribute("href")
                        text = e.inner_text().strip()[:100]
                        if href:
                            links.append({"href": href, "text": text})
                    except Exception:
                        continue
                result["links"] = links
                result["count"] = len(links)

            elif action == "table":
                if not args:
                    return {"status": "error", "error": "table requires a CSS selector argument"}
                selector = _validate_selector(args[0])
                try:
                    rows = page.locator(selector).all()
                except Exception as e:
                    return {"status": "error", "error": f"Failed to query table: {str(e)[:300]}"}
                table_data = []
                for row in rows[:MAX_TABLE_ROWS]:
                    try:
                        cells = row.locator("td, th").all()
                        table_data.append([c.inner_text().strip() for c in cells])
                    except Exception:
                        continue
                if not table_data:
                    return {"status": "error", "error": f"No table rows found for selector: {selector}"}
                result["table"] = table_data
                result["rows"] = len(table_data)

            elif action == "evaluate":
                if not args:
                    return {"status": "error", "error": "evaluate requires JavaScript code argument"}
                js = args[0]
                if not js or not js.strip():
                    return {"status": "error", "error": "evaluate requires non-empty JavaScript code"}
                if len(js) > 10000:
                    return {"status": "error", "error": "JavaScript code too long (max 10000 characters)"}
                try:
                    evaluated = page.evaluate(js)
                except Exception as e:
                    return {"status": "error", "error": f"JavaScript evaluation failed: {str(e)[:500]}"}
                try:
                    json.dumps(evaluated)
                    result["evaluated"] = evaluated
                except (TypeError, ValueError):
                    result["evaluated"] = str(evaluated)[:10000]

            elif action == "pdf":
                suffix = os.urandom(4).hex()
                tmp = os.path.join(tempfile.gettempdir(), f"delux_page_{suffix}.pdf")
                try:
                    page.pdf(path=tmp)
                except PermissionError:
                    return {"status": "error", "error": f"Permission denied writing PDF to {tmp}"}
                except Exception as e:
                    return {"status": "error", "error": f"Failed to generate PDF: {str(e)[:300]}"}
                if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
                    return {"status": "error", "error": "PDF file is empty or was not created"}
                result["file"] = tmp
                result["preview"] = f"PDF saved: {tmp}"

            else:
                return {"status": "error", "error": f"Unknown action: {action}"}

    except Exception as e:
        return {
            "status": "error",
            "error": f"Unexpected browser error: {str(e)[:500]}",
        }
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass

    return result


def browser(action: str, url: str, *args: str, **kwargs: str) -> str:
    """Main browser entry point. Returns JSON string."""
    try:
        action = _validate_action(action)
    except ValueError as e:
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

    try:
        url = _validate_url(url)
    except ValueError as e:
        if action == "screenshot" and not url:
            pass
        else:
            return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

    try:
        viewport = _validate_viewport(kwargs.get("viewport"))
    except ValueError as e:
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

    try:
        timeout = _validate_timeout(kwargs.get("timeout"))
    except ValueError as e:
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

    try:
        result = _browser_action(action, url, *args, viewport=viewport, timeout=timeout)
    except Exception:
        result = {
            "status": "error",
            "error": f"Unhandled browser error: {traceback.format_exc()[:1000]}",
        }

    return json.dumps(result, indent=2, ensure_ascii=False, default=str)


_BOOLEAN_FLAGS = {"--json"}
_FLAGS_WITH_VALUE = {"--viewport", "--timeout"}


def _parse_cli(argv: list[str]) -> dict:
    """Parse CLI arguments. Returns dict with action, url, args, and kwargs."""
    positional: list[str] = []
    kwargs: dict[str, str] = {}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg.startswith("--"):
            if "=" in arg:
                key, _, val = arg[2:].partition("=")
                kwargs[key.replace("-", "_")] = val
            elif arg in _BOOLEAN_FLAGS:
                kwargs[arg[2:].replace("-", "_")] = "true"
            else:
                key = arg[2:].replace("-", "_")
                if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                    i += 1
                    kwargs[key] = argv[i]
                else:
                    kwargs[key] = "true"
        else:
            positional.append(arg)
        i += 1
    return {
        "action": positional[0] if len(positional) > 0 else "",
        "url": positional[1] if len(positional) > 1 else "",
        "args": positional[2:] if len(positional) > 2 else [],
        "kwargs": kwargs,
    }


def _print_json(status: str, data: dict | None = None, error: str | None = None) -> None:
    """Print a standardized JSON response and exit."""
    if status == "error":
        print(json.dumps({"status": "error", "error": error or "Unknown error"}, ensure_ascii=False))
    else:
        payload = {"status": "ok", "data": data or {}}
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    try:
        parsed = _parse_cli(sys.argv[1:])

        action = parsed["action"]
        url = parsed["url"]
        args = parsed["args"]
        kwargs = parsed["kwargs"]

        if not action:
            usage = (
                "delux-browser <action> <url> [args...] [--viewport WIDTHxHEIGHT] "
                "[--timeout MS] [--json]\n"
                "Actions: screenshot, html, text, click, fill, links, table, evaluate, pdf\n"
                "Examples:\n"
                "  delux-browser screenshot https://example.com\n"
                "  delux-browser html https://example.com\n"
                "  delux-browser click https://example.com '#button'\n"
                "  delux-browser evaluate https://example.com 'document.title'"
            )
            _print_json("error", error=usage)
            sys.exit(1)

        output = browser(action, url, *args, **kwargs)
        print(output)
        sys.exit(0)

    except KeyboardInterrupt:
        _print_json("error", error="Interrupted by user (Ctrl+C)")
        sys.exit(130)
    except Exception:
        _print_json("error", error=f"Unhandled CLI error: {traceback.format_exc()[:1000]}")
        sys.exit(1)
