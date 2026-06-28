import json
import os
import re
import sys
import tempfile
from urllib.parse import urlparse


def _try_playwright(action: str, url: str, *args) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"error": "playwright not installed. Install with: pip install playwright && python3 -m playwright install chromium"}

    result: dict = {"action": action, "url": url, "status": "ok"}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_default_timeout(15000)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)

            if action == "screenshot":
                selector = args[0] if args else None
                tmp = os.path.join(tempfile.gettempdir(), f"delux_screenshot_{os.urandom(4).hex()}.png")
                if selector:
                    page.wait_for_selector(selector, timeout=10000)
                    page.locator(selector).screenshot(path=tmp)
                else:
                    page.screenshot(path=tmp, full_page=True)
                result["file"] = tmp
                result["preview"] = f"Screenshot saved: {tmp}"

            elif action == "html":
                result["html"] = page.content()

            elif action == "text":
                if args:
                    page.wait_for_selector(args[0], timeout=10000)
                    els = page.locator(args[0]).all()
                    result["text"] = "\n".join(e.inner_text() for e in els)
                else:
                    result["text"] = page.locator("body").inner_text()

            elif action == "click":
                if not args:
                    return {"error": "click requires a CSS selector"}
                page.wait_for_selector(args[0], timeout=10000)
                page.click(args[0])
                page.wait_for_timeout(1000)
                result["html"] = page.content()
                result["text"] = page.locator("body").inner_text()

            elif action == "fill":
                if len(args) < 2:
                    return {"error": "fill requires selector and text"}
                page.wait_for_selector(args[0], timeout=10000)
                page.fill(args[0], args[1])
                result["status"] = f"filled '{args[0]}' with '{args[1][:50]}'"

            elif action == "links":
                selector = args[0] if args else "a[href]"
                els = page.locator(selector).all()
                links = []
                for e in els:
                    href = e.get_attribute("href")
                    text = e.inner_text().strip()[:100]
                    if href:
                        links.append({"href": href, "text": text})
                result["links"] = links
                result["count"] = len(links)

            elif action == "table":
                if not args:
                    return {"error": "table requires a CSS selector"}
                rows = page.locator(args[0]).all()
                table_data = []
                for row in rows:
                    cells = row.locator("td, th").all()
                    table_data.append([c.inner_text().strip() for c in cells])
                result["table"] = table_data
                result["rows"] = len(table_data)

            elif action == "evaluate":
                if not args:
                    return {"error": "evaluate requires JavaScript code"}
                js = args[0]
                result["evaluated"] = page.evaluate(js)

            else:
                return {"error": f"Unknown action: {action}"}

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)[:500]
        finally:
            browser.close()

    return result


def browser(action: str, url: str, *args) -> str:
    if not url and action not in ("screenshot",):
        return json.dumps({"error": "URL is required"})

    if not urlparse(url).scheme:
        url = "https://" + url

    result = _try_playwright(action, url, *args)
    return json.dumps(result, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: delux-browser <action> <url> [args...]"}))
        sys.exit(1)
    action = sys.argv[1]
    url = sys.argv[2]
    args = sys.argv[3:]
    print(browser(action, url, *args))
