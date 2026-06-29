#!/usr/bin/env python3
"""
DDG-AI Proxy -- OpenAI-compatible API backed by DuckDuckGo AI Chat (free).

Uses Playwright with system Chromium to interact with duck.ai.
Browser runs in a dedicated thread with a request queue for thread safety.

Start:  python proxy.py
Usage:  curl -X POST http://localhost:8765/v1/chat/completions \
            -H "Content-Type: application/json" \
            -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Hello"}]}'
"""

from __future__ import annotations

import argparse
import http.server
import json
import queue
import sys
import threading
from dataclasses import dataclass, field

# ── Available models on DDG AI Chat ──────────────────────────────────────────

DDG_MODELS = [
    "gpt-4o-mini",
    "claude-3-haiku",
    "llama-3.3-70b",
    "mistral-small-3",
    "o3-mini",
    "gpt-5.4-nano",
]

DEFAULT_MODEL = "gpt-4o-mini"


# ── Chat request / response ──────────────────────────────────────────────────

@dataclass
class ChatRequest:
    message: str
    model: str
    timeout: int
    result_queue: queue.Queue = field(default_factory=queue.Queue)


# ── Browser manager for DDG AI Chat ──────────────────────────────────────────

STEALTH_SCRIPT = """
// Anti-detection: hide automation signals from DDG
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = { runtime: {} };
"""

CONSENT_SCRIPT = (
    "var b=document.querySelectorAll('button');"
    "for(var i=0;i<b.length;i++){"
    "if(b[i].textContent.trim()==='Continue'&&b[i].offsetParent!==null){b[i].click();}}"
)

EXTRACT_SCRIPT = """
() => {
    // Walk the page in reverse to find the last AI response
    const messages = document.querySelectorAll(
        '[class*="assistantText"], [class*="messageText"], [class*="prose"]'
    );
    let last = '';
    for (const m of messages) {
        const t = m.textContent?.trim();
        if (t && t.length > 3) last = t;
    }
    if (last) return last;

    // Fallback: extract all substantial text blocks after the prompt
    const body = document.body.innerText;
    const lines = body.split('\\n').filter(l => l.trim().length > 10);
    // Return the last substantial line that's not UI chrome
    const skipWords = ['Duck.ai', 'New Chat', 'Settings', 'Tools', 'Fast',
                        'Download', 'All chats', 'Privacy', 'Continue', 'Free',
                        'Get the App', 'Anonymized', 'Drop your'];
    for (let i = lines.length - 1; i >= 0; i--) {
        const line = lines[i].trim();
        if (skipWords.some(w => line.startsWith(w))) continue;
        if (line.length > 5) return line;
    }
    return '';
}
"""


class DDGBrowser:
    """Manages a single Playwright browser instance in its own thread."""

    def __init__(self):
        self._request_queue: queue.Queue = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None
        self._browser = None
        self._context = None
        self._page = None
        self._consent_done = False
        self._ready = threading.Event()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=30):
            raise RuntimeError("Browser failed to start within 30s")

    def _run(self) -> None:
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        try:
            self._browser = pw.chromium.launch(
                headless=True,
                channel="chromium",
                args=[
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            self._context = self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            self._page = self._context.new_page()
            self._page.add_init_script(STEALTH_SCRIPT)
            self._ready.set()

            print("[DDG] Browser ready", file=sys.stderr)

            while self._running:
                try:
                    req = self._request_queue.get(timeout=1)
                except queue.Empty:
                    continue

                try:
                    result = self._do_chat(req.message, req.model, req.timeout)
                    req.result_queue.put(("ok", result))
                except Exception as exc:
                    req.result_queue.put(("error", str(exc)))
        finally:
            try:
                if self._browser:
                    self._browser.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
                pass

    def _handle_consent(self) -> None:
        """Accept the privacy consent dialog."""
        page = self._page
        try:
            page.goto(
                "https://duck.ai/chat?ia=chat&duckai=1",
                wait_until="domcontentloaded",
                timeout=15000,
            )
        except Exception:
            pass
        page.wait_for_timeout(2000)

        # Trigger consent by sending a dummy message
        try:
            page.fill("textarea", "x")
            page.keyboard.press("Enter")
            page.wait_for_timeout(3000)
        except Exception:
            pass

        # Click Continue via JS
        try:
            page.evaluate(CONSENT_SCRIPT)
            page.wait_for_timeout(3000)
            print("[DDG] Consent accepted", file=sys.stderr)
        except Exception as e:
            print(f"[DDG] Consent eval error: {e}", file=sys.stderr)
            print("[DDG] Consent not needed", file=sys.stderr)

    def _do_chat(self, message: str, model: str, timeout: int) -> str:
        """Send a chat message using the browser page. Must be called from browser thread."""
        page = self._page

        # Navigate to fresh chat
        try:
            page.goto(
                "https://duck.ai/chat?ia=chat&duckai=1",
                wait_until="domcontentloaded",
                timeout=15000,
            )
        except Exception:
            pass
        page.wait_for_timeout(2000)

        # Handle consent if needed
        if not self._consent_done:
            self._handle_consent()
            self._consent_done = True

            # After consent, reload for a clean chat
            try:
                page.goto(
                    "https://duck.ai/chat?ia=chat&duckai=1",
                    wait_until="domcontentloaded",
                    timeout=15000,
                )
            except Exception:
                pass
            page.wait_for_timeout(2000)

        # Select model if not default
        if model != DEFAULT_MODEL and model in DDG_MODELS:
            try:
                # Click the model selector and choose
                page.evaluate("""(modelName) => {
                    const buttons = document.querySelectorAll('button');
                    for (const b of buttons) {
                        if (b.textContent.includes(modelName)) {
                            b.click();
                            return;
                        }
                    }
                }""", model)
                page.wait_for_timeout(1000)
            except Exception:
                pass

        # Type and submit
        page.fill("textarea", message)
        page.keyboard.press("Enter")

        # Wait for AI response
        wait_ms = min(timeout * 1000, 90000)
        try:
            # Wait for the response to appear (look for the model name label)
            page.wait_for_selector('text=/GPT|Claude|Llama|Mistral|o3/', timeout=timeout * 1000)
        except Exception:
            pass
        page.wait_for_timeout(3000)

        # Extract response text
        extract_js = (
            "(function(){var m=document.querySelectorAll("
            "'[class*=\"assistantText\"],[class*=\"messageText\"],[class*=\"prose\"]');"
            "var l='';for(var i=0;i<m.length;i++){var t=m[i].textContent.trim();"
            "if(t&&t.length>2)l=t;}if(l)return l;"
            "var b=document.body.innerText.split(String.fromCharCode(10))"
            ".filter(function(x){return x.trim().length>2;});"
            "var s=['Duck.ai','New Chat','Settings','Tools','Fast',"
            "'Download','All chats','Privacy','Continue','Free',"
            "'Get the App','Anonymized','Drop your','GPT','Claude','Llama','Mistral','o3'];"
            "var prompt='';var foundPrompt=false;"
            "for(var j=0;j<b.length;j++){"
            "  var ln=b[j].trim();"
            "  if(!foundPrompt&&ln.length>2&&!s.some(function(w){return ln.indexOf(w)===0;})){prompt=ln;foundPrompt=true;}"
            "}"
            "for(var j=b.length-1;j>=0;j--){var ln=b[j].trim();"
            "if(ln!==prompt&&!s.some(function(w){return ln.indexOf(w)===0;})&&ln.length>2)return ln;}"
            "return '';})()"
        )
        response = page.evaluate(extract_js)
        return response.strip() if response else ""

    def chat(self, message: str, model: str = DEFAULT_MODEL, timeout: int = 45) -> str:
        """Queue a chat request and wait for the result. Thread-safe."""
        req = ChatRequest(message=message, model=model, timeout=timeout)
        self._request_queue.put(req)

        try:
            status, result = req.result_queue.get(timeout=timeout + 30)
        except queue.Empty:
            raise RuntimeError("Chat request timed out")

        if status == "error":
            raise RuntimeError(result)
        return result

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)


# ── Global browser instance ──────────────────────────────────────────────────

g_browser: DDGBrowser | None = None


def get_browser() -> DDGBrowser:
    global g_browser
    if g_browser is None:
        g_browser = DDGBrowser()
        g_browser.start()
    return g_browser


# ── HTTP Proxy Handler ───────────────────────────────────────────────────────

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    """OpenAI-compatible HTTP handler backed by DDG AI Chat."""

    def log_message(self, fmt: str, *args) -> None:
        if args[0].startswith("4") or args[0].startswith("5"):
            print(f"[DDG-Proxy] {args[0]} {args[1]} {args[2]}", file=sys.stderr)

    def _json(self, status: int, data: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path in ("/health", "/"):
            self._json(200, {
                "status": "ok",
                "service": "ddg-ai-proxy",
                "backend": "DuckDuckGo AI Chat (via Playwright + Chromium)",
                "endpoints": {
                    "chat": "/v1/chat/completions",
                    "models": "/v1/models",
                    "health": "/health",
                },
                "models": DDG_MODELS,
            })
        elif self.path == "/v1/models":
            self._json(200, {
                "object": "list",
                "data": [
                    {"id": m, "object": "model", "created": 0, "owned_by": "duckduckgo"}
                    for m in DDG_MODELS
                ],
            })
        else:
            self._json(404, {"error": {"message": "Not found", "type": "invalid_request_error"}})

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": {"message": "Not found", "type": "invalid_request_error"}})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._json(400, {"error": {"message": "Empty request body", "type": "invalid_request_error"}})
            return

        raw = self.rfile.read(content_length)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            self._json(400, {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}})
            return

        messages: list[dict] = body.get("messages", [])
        model: str = body.get("model", DEFAULT_MODEL)

        if not messages:
            self._json(400, {"error": {"message": "No messages provided", "type": "invalid_request_error"}})
            return

        if model not in DDG_MODELS:
            model = DEFAULT_MODEL

        user_content = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_content = str(m.get("content", ""))
                break

        if not user_content:
            self._json(400, {"error": {"message": "No user message found", "type": "invalid_request_error"}})
            return

        print(f"[DDG-Proxy] Sending: {user_content[:100]}...", file=sys.stderr)

        try:
            browser = get_browser()
            response_text = browser.chat(user_content, model)
        except Exception as exc:
            print(f"[DDG-Proxy] ERROR: {exc}", file=sys.stderr)
            self._json(502, {
                "error": {
                    "message": f"DuckDuckGo AI Chat error: {exc}",
                    "type": "proxy_error",
                }
            })
            return

        print(f"[DDG-Proxy] Response: {response_text[:100]}...", file=sys.stderr)

        self._json(200, {
            "id": f"ddg-{abs(hash(response_text)) & 0x7FFFFFFF:08x}",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response_text,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        })


# ── Server entry point ───────────────────────────────────────────────────────

def run_proxy(host: str = "127.0.0.1", port: int = 8765) -> None:
    print(" Initializing browser...", file=sys.stderr)
    try:
        get_browser()
    except Exception as exc:
        print(f" WARNING: Browser init failed: {exc}", file=sys.stderr)
        print(f" Install chromium: sudo pacman -S chromium", file=sys.stderr)

    server = http.server.HTTPServer((host, port), ProxyHandler)
    server.timeout = 1

    print(f"\n DDG-AI Proxy started", file=sys.stderr)
    print(f"   Listening: http://{host}:{port}", file=sys.stderr)
    print(f"   Chat endpoint: POST http://{host}:{port}/v1/chat/completions", file=sys.stderr)
    print(f"   Health check:  GET  http://{host}:{port}/health", file=sys.stderr)
    print(f"   Models:        GET  http://{host}:{port}/v1/models", file=sys.stderr)
    print(f"", file=sys.stderr)
    print(f"   Available models: {', '.join(DDG_MODELS)}", file=sys.stderr)
    print(f"   Default model:    {DEFAULT_MODEL}", file=sys.stderr)
    print(f"", file=sys.stderr)
    print(f" Press Ctrl+C to stop", file=sys.stderr)
    print(f"", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n Shutting down...", file=sys.stderr)
        if g_browser:
            g_browser.stop()
        server.shutdown()


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="DDG-AI Proxy - Free OpenAI-compatible API via DuckDuckGo AI Chat"
    )
    p.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    p.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    args = p.parse_args()
    run_proxy(host=args.host, port=args.port)
