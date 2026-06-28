#!/usr/bin/env python3
"""Mock LLM API server — simula llama.cpp en 127.0.0.1:11434.

Captura y guarda TODAS las requests para depurar el prompt que Delux envía al modelo.
Cada request se loguea a `mock_requests.log` con:
  - Timestamp
  - System prompt completo
  - Mensajes del usuario
  - Modelo solicitado
  - Tokens estimados

Uso:
    uv run python scripts/mock_llm.py               # loguea todo
    uv run python scripts/mock_llm.py --verbose     # también muestra en stdout
    uv run python scripts/mock_llm.py --no-save     # no guarda a disco
    uv run python scripts/mock_llm.py --port 11435  # puerto alternativo
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

LOG_FILE = Path(__file__).parent.parent / "mock_requests.log"
COUNTER = [0]  # mutable for closure

# ── ANSI ──
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
DIM = "\033[2m"
RESET = "\033[0m"


def estimate_tokens(text: str) -> int:
    """Estimación rápida de tokens (~4 chars por token para inglés, ~3 para español)."""
    return len(text) // 4


def extract_json_from_content(content: str) -> dict | None:
    """Extrae la acción JSON del contenido del modelo (respuesta mock)."""
    matches = re.findall(r'\{[^{}]*"action"[^{}]*\}', content, re.DOTALL)
    if matches:
        try:
            return json.loads(matches[0])
        except json.JSONDecodeError:
            pass
    return None


class MockHandler(BaseHTTPRequestHandler):
    verbose: bool = False
    no_save: bool = False

    def log_message(self, format, *args):
        pass  # silence default logging

    def do_GET(self):
        if self.path in ("/v1/models", "/models"):
            self._json_response(200, {
                "object": "list",
                "data": [
                    {"id": "delux-mock", "object": "model", "owned_by": "mock"},
                ],
            })
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self):
        if self.path not in ("/v1/chat/completions", "/chat/completions"):
            self._json_response(404, {"error": f"unknown endpoint: {self.path}"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._json_response(400, {"error": "empty body"})
            return

        raw_body = self.rfile.read(content_length)
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            self._json_response(400, {"error": "invalid JSON"})
            return

        model = body.get("model", "?")
        messages = body.get("messages", [])
        temperature = body.get("temperature", 1.0)
        max_tokens = body.get("max_tokens", 512)
        stream = body.get("stream", False)

        # ── Analizar request ──
        system_prompt = ""
        user_messages = []
        total_system_tokens = 0
        total_user_tokens = 0
        total_tool_tokens = 0
        for msg in messages:
            role = msg.get("role", "")
            content = str(msg.get("content", ""))
            if role == "system":
                system_prompt = content
                total_system_tokens += estimate_tokens(content)
            elif role == "user":
                user_messages.append(content)
                total_user_tokens += estimate_tokens(content)
            elif role in ("assistant", "tool"):
                total_tool_tokens += estimate_tokens(content)

        total_est_tokens = total_system_tokens + total_user_tokens + total_tool_tokens

        # ── Mock response ──
        # Generar una respuesta genérica que intente ser útil
        last_user = user_messages[-1] if user_messages else ""

        # Intentar extraer un patrón común
        fake_action = {}
        if "read_file" in last_user.lower() or "lee" in last_user.lower():
            fake_action = {"action": "read_file", "path": "README.md"}
        elif "write_file" in last_user.lower() or "crea" in last_user.lower() or "escribe" in last_user.lower():
            fake_action = {"action": "write_file", "path": "output.txt", "content": "mock content"}
        elif "shell" in last_user.lower() or "ejecuta" in last_user.lower():
            fake_action = {"action": "shell", "command": "echo 'mock result'"}
        elif "edit_file" in last_user.lower() or "cambia" in last_user.lower():
            fake_action = {"action": "edit_file", "path": "file.txt", "old_str": "old", "new_str": "new"}
        elif "search" in last_user.lower() or "busca" in last_user.lower():
            fake_action = {"action": "search_files", "query": "mock query"}
        elif "final" in last_user.lower() or "termina" in last_user.lower() or "resume" in last_user.lower():
            fake_action = {"action": "final", "message": "Tarea completada (mock)."}
        else:
            fake_action = {"action": "final", "message": "Mock response — task simulated."}

        # Inyectar en <action> tag si el system prompt usa ese formato
        response_content = ""
        if "<action>" in system_prompt or "action_format" in system_prompt.lower() or "action" in last_user.lower():
            response_content = f"<action>\n{json.dumps(fake_action, indent=2)}\n</action>"
        else:
            response_content = json.dumps(fake_action)

        COUNTER[0] += 1
        req_num = COUNTER[0]

        # ── Log ──
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        log_lines = [
            f"\n{'═' * 80}",
            f"REQUEST #{req_num}  |  {now}  |  model={model}  |  temp={temperature}",
            f"{'═' * 80}",
            f"",
            f"┌─ TOKENS ESTIMADOS ─────────────────────────────",
            f"│ System:  {total_system_tokens:>8,}",
            f"│ User:    {total_user_tokens:>8,}",
            f"│ Tool/As: {total_tool_tokens:>8,}",
            f"│ TOTAL:   {total_est_tokens:>8,}",
            f"│ Messages: {len(messages)}",
            f"│ Max output: {max_tokens}",
            f"└─────────────────────────────────────────────────",
        ]

        # Extract skill summary from system prompt
        skills_match = re.search(r'SKILLS:\n(.*?)(?:\n\n|\nDOCS|\n<memory|\Z)', system_prompt, re.DOTALL)
        if skills_match:
            skills_section = skills_match.group(1)
            skill_count = len(re.findall(r'^- ', skills_section, re.MULTILINE))
            log_lines.append(f"\n┌─ SKILLS ({skill_count}) ──────────────────────────────")
            for line in skills_section.split("\n")[:20]:
                log_lines.append(f"│ {line[:120]}")
            if skill_count > 20:
                log_lines.append(f"│ ... ({skill_count - 20} more)")
            log_lines.append(f"└─────────────────────────────────────────────────")

        # Extract memory section
        memory_match = re.search(r'<memory-context>(.*?)</memory-context>', system_prompt, re.DOTALL)
        if memory_match:
            mem_text = memory_match.group(1).strip()
            mem_lines = mem_text.split("\n")
            log_lines.append(f"\n┌─ MEMORY ({len(mem_lines)} lines, {estimate_tokens(mem_text):,} tokens) ───────")
            for line in mem_lines[:15]:
                log_lines.append(f"│ {line[:120]}")
            if len(mem_lines) > 15:
                log_lines.append(f"│ ... ({len(mem_lines) - 15} more lines)")
            log_lines.append(f"└─────────────────────────────────────────────────")

        # Extract docs section
        docs_match = re.search(r'DOCS:\n(.*?)(?:\n\n|\n<|\Z)', system_prompt, re.DOTALL)
        if docs_match:
            docs_text = docs_match.group(1).strip()
            docs_size = estimate_tokens(docs_text)
            log_lines.append(f"\n┌─ DOCS ({docs_size:,} tokens) ────────────────────────────")
            for line in docs_text.split("\n")[:10]:
                log_lines.append(f"│ {line[:120]}")
            log_lines.append(f"└─────────────────────────────────────────────────")

        # System prompt header/footer analysis
        sp_lines = system_prompt.split("\n")
        log_lines.append(f"\n┌─ SYSTEM PROMPT ─────────────────────────────────")
        log_lines.append(f"│ Total chars: {len(system_prompt):,}")
        log_lines.append(f"│ Total lines: {len(sp_lines):,}")
        log_lines.append(f"│ Total tokens (est): {total_system_tokens:,}")
        log_lines.append(f"└─────────────────────────────────────────────────")

        # User messages
        log_lines.append(f"\n┌─ USER MESSAGES ({len(user_messages)}) ────────────────────")
        for i, um in enumerate(user_messages[-5:]):
            preview = um[:300].replace("\n", "\\n")
            log_lines.append(f"│ [{i+1}] ({estimate_tokens(um)} tokens) {preview}")
        log_lines.append(f"└─────────────────────────────────────────────────")

        # Response
        log_lines.append(f"\n┌─ MOCK RESPONSE ────────────────────────────────")
        log_lines.append(f"│ {json.dumps(fake_action)}")
        log_lines.append(f"└─────────────────────────────────────────────────")

        log_text = "\n".join(log_lines)

        # Output
        if MockHandler.verbose or not MockHandler.no_save:
            print(log_text)
        if not MockHandler.no_save:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(log_text + "\n")

        # ── Stream or non-stream response ──
        if stream:
            self._stream_response(model, response_content, req_num)
        else:
            self._json_response(200, {
                "id": f"chatcmpl-{req_num}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response_content,
                    },
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": total_est_tokens,
                    "completion_tokens": estimate_tokens(response_content),
                    "total_tokens": total_est_tokens + estimate_tokens(response_content),
                },
            })

    def _json_response(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _stream_response(self, model: str, content: str, req_num: int):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        chunks = [content[i:i+4] for i in range(0, len(content), 4)] or [" "]

        for i, chunk in enumerate(chunks):
            delta = {"role": "assistant", "content": ""} if i == 0 else {"content": chunk}
            data = {
                "id": f"chatcmpl-{req_num}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            }
            line = f"data: {json.dumps(data)}\n\n"
            self.wfile.write(line.encode("utf-8"))
            self.wfile.flush()
            time.sleep(0.01)

        # Finish
        finish = {
            "id": f"chatcmpl-{req_num}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        self.wfile.write(f"data: {json.dumps(finish)}\n\n".encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def main():
    parser = argparse.ArgumentParser(description="Mock LLM API para depurar Delux Agent")
    parser.add_argument("--port", type=int, default=11434, help="Puerto (default: 11434)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Mostrar requests en stdout también")
    parser.add_argument("--no-save", action="store_true", help="No guardar a mock_requests.log")
    args = parser.parse_args()

    MockHandler.verbose = args.verbose
    MockHandler.no_save = args.no_save

    server = HTTPServer(("127.0.0.1", args.port), MockHandler)

    print(f"\n{BOLD}{CYAN}╔══════════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{CYAN}║{RESET}  {BOLD}Mock LLM API — Delux Debug Proxy{RESET}                   {BOLD}{CYAN}║{RESET}")
    print(f"{BOLD}{CYAN}╠══════════════════════════════════════════════════════╣{RESET}")
    print(f"{BOLD}{CYAN}║{RESET}  {DIM}Endpoint:{RESET}  http://127.0.0.1:{args.port}/v1/chat/completions     {BOLD}{CYAN}║{RESET}")
    print(f"{BOLD}{CYAN}║{RESET}  {DIM}Models:{RESET}    http://127.0.0.1:{args.port}/v1/models                {BOLD}{CYAN}║{RESET}")
    print(f"{BOLD}{CYAN}║{RESET}  {DIM}Log file:{RESET}  {LOG_FILE}  {BOLD}{CYAN}║{RESET}")
    print(f"{BOLD}{CYAN}║{RESET}  {DIM}Verbose:{RESET}  {GREEN if args.verbose else RED}{args.verbose}{RESET}                                {BOLD}{CYAN}║{RESET}")
    print(f"{BOLD}{CYAN}║{RESET}  {DIM}Save:{RESET}     {GREEN if not args.no_save else RED}{not args.no_save}{RESET}                                {BOLD}{CYAN}║{RESET}")
    print(f"{BOLD}{CYAN}╚══════════════════════════════════════════════════════╝{RESET}")
    print(f"\n{YELLOW}⚠  Asegúrate de que Delux apunte a http://127.0.0.1:{args.port}/v1{RESET}")
    print(f"   {DIM}Model: 'delux-mock' (cualquier nombre funciona){RESET}")
    print(f"   {DIM}Ctrl+C para detener{RESET}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{GREEN}✓{RESET} Mock server stopped. {COUNTER[0]} requests logged.")
        server.server_close()


if __name__ == "__main__":
    main()
