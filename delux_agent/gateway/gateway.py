from __future__ import annotations

import json
import logging
import os
import random
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

TELEGRAM_CONFIG_PATH = os.path.expanduser("~/.delux/telegram.json")
MAX_MESSAGE_LENGTH = 4000
MAX_RETRIES = 5
BASE_RETRY_DELAY = 1.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("delux-gateway")


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_markdown(text: str) -> str:
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, "\\" + ch)
    return text


@dataclass
class TelegramConfig:
    token: str
    chat_ids: list[str]

    @classmethod
    def load(cls) -> TelegramConfig | None:
        if not os.path.exists(TELEGRAM_CONFIG_PATH):
            return None
        try:
            data = json.loads(Path(TELEGRAM_CONFIG_PATH).read_text(encoding="utf-8"))
            token = data.get("token", "").strip()
            raw_ids = data.get("chat_id") or data.get("chat_ids") or []
            if isinstance(raw_ids, str):
                chat_ids = [raw_ids.strip()]
            elif isinstance(raw_ids, list):
                chat_ids = [str(c).strip() for c in raw_ids]
            else:
                return None
            if token and chat_ids:
                return cls(token=token, chat_ids=chat_ids)
        except Exception:
            pass
        return None


_current_task: threading.Event | None = None
_current_task_lock = threading.Lock()


def _cancel_current() -> bool:
    global _current_task
    with _current_task_lock:
        if _current_task:
            _current_task.set()
            _current_task = None
            return True
    return False


def _register_task() -> threading.Event:
    global _current_task
    ev = threading.Event()
    with _current_task_lock:
        _current_task = ev
    return ev


def _unregister_task() -> None:
    global _current_task
    with _current_task_lock:
        _current_task = None


def _api_request(
    token: str, method: str, params: dict | None = None,
    timeout: int = 15, retries: int = MAX_RETRIES,
) -> dict | None:
    url = f"https://api.telegram.org/bot{token}/{method}"
    for attempt in range(retries):
        data = urllib.parse.urlencode(params).encode("utf-8") if params else None
        try:
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            if result.get("ok"):
                return result.get("result")
            desc = result.get("description", "")
            if "Too Many Requests" in desc:
                delay = (attempt + 1) * 2.0
                log.warning("Rate limited, waiting %.1fs", delay)
                time.sleep(delay)
                continue
            if "can't parse entities" in desc:
                params_clean = dict(params or {})
                params_clean.pop("parse_mode", None)
                return _api_request(token, method, params_clean, timeout, retries)
            if "message to edit not found" in desc:
                return None
            log.warning("API error: %s", desc)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                delay = (attempt + 1) * 2.0
                log.warning("HTTP 429, waiting %.1fs", delay)
                time.sleep(delay)
                continue
            log.warning("HTTP %d: %s", e.code, str(e)[:100])
        except (urllib.error.URLError, OSError) as e:
            if attempt < retries - 1:
                delay = BASE_RETRY_DELAY * (2 ** attempt) + random.uniform(0, 1)
                log.warning("Connection error, retry %d in %.1fs: %s", attempt + 1, delay, str(e)[:80])
                time.sleep(delay)
                continue
            log.error("Failed after %d retries: %s", retries, str(e)[:100])
    return None


def _send_raw(
    token: str, chat_id: str, text: str,
    parse_mode: str = "", disable_preview: bool = True,
    reply_markup: dict | None = None,
) -> int | None:
    params = {
        "chat_id": chat_id,
        "text": text[:MAX_MESSAGE_LENGTH],
        "link_preview_options": json.dumps({"is_disabled": disable_preview}),
    }
    if parse_mode:
        params["parse_mode"] = parse_mode
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    result = _api_request(token, "sendMessage", params)
    if result and isinstance(result, dict):
        return result.get("message_id")
    return None


def send_message(token: str, chat_id: str, text: str, **kwargs) -> int | None:
    """Send plain text — everything is escaped, no parse_mode."""
    return _send_raw(token, chat_id, escape_html(text), parse_mode="", **kwargs)


def send_html(token: str, chat_id: str, html_text: str, **kwargs) -> int | None:
    """Send pre-formatted HTML — caller is responsible for escaping variables."""
    return _send_raw(token, chat_id, html_text, parse_mode="HTML", **kwargs)


def edit_message(
    token: str, chat_id: str, message_id: int, text: str,
    parse_mode: str = "", reply_markup: dict | None = None,
) -> bool:
    params = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text[:MAX_MESSAGE_LENGTH],
    }
    if parse_mode:
        params["parse_mode"] = parse_mode
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    return _api_request(token, "editMessageText", params) is not None


def edit_html(token: str, chat_id: str, message_id: int, html_text: str) -> bool:
    return edit_message(token, chat_id, message_id, html_text, parse_mode="HTML")


def delete_message(token: str, chat_id: str, message_id: int) -> None:
    _api_request(token, "deleteMessage", {"chat_id": chat_id, "message_id": message_id})


def send_action(token: str, chat_id: str, action: str) -> None:
    _api_request(token, "sendChatAction", {"chat_id": chat_id, "action": action})


def send_chunked_plain(token: str, chat_id: str, text: str) -> None:
    remaining = text
    while remaining:
        chunk = remaining[:MAX_MESSAGE_LENGTH]
        remaining = remaining[MAX_MESSAGE_LENGTH:]
        send_message(token, chat_id, chunk)
        time.sleep(0.35)


def send_chunked_html(token: str, chat_id: str, html_text: str) -> None:
    remaining = html_text
    while remaining:
        chunk = remaining[:MAX_MESSAGE_LENGTH]
        remaining = remaining[MAX_MESSAGE_LENGTH:]
        send_html(token, chat_id, chunk)
        time.sleep(0.35)


def build_inline_keyboard(buttons: list[list[tuple[str, str]]]) -> dict:
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": data} for label, data in row]
            for row in buttons
        ]
    }


@dataclass
class GatewaySession:
    chat_id: str
    history: list[dict] = field(default_factory=list)
    last_message_id: int | None = None
    status_message_id: int | None = None

    def add_turn(self, user: str, assistant: str) -> None:
        self.history.append({"user": user, "assistant": assistant})
        if len(self.history) > 10:
            self.history = self.history[-10:]


_session_store: dict[str, GatewaySession] = {}
_session_lock = threading.Lock()


def get_session(chat_id: str) -> GatewaySession:
    with _session_lock:
        if chat_id not in _session_store:
            _session_store[chat_id] = GatewaySession(chat_id=chat_id)
        return _session_store[chat_id]


class GatewayEventHandler:
    def __init__(self, token: str, chat_id: str, session: GatewaySession):
        self.token = token
        self.chat_id = chat_id
        self.session = session
        self._step = 0
        self._cancel_flag: threading.Event | None = None

    def set_cancel_flag(self, ev: threading.Event) -> None:
        self._cancel_flag = ev

    def _status(self, text: str, edit: bool = True) -> None:
        html = f"<code>{escape_html(text)}</code>"
        if not self.session.status_message_id:
            mid = send_html(self.token, self.chat_id, html)
            if mid:
                self.session.status_message_id = mid
        elif edit:
            edit_html(self.token, self.chat_id, self.session.status_message_id, html)

    def __call__(self, event: str, payload: dict) -> None:
        if self._cancel_flag and self._cancel_flag.is_set():
            return
        if event == "action_started":
            self._step += 1
            action = payload.get("action", {})
            kind = action.get("action", "")
            emoji = {"shell": "⚡", "write_file": "📝", "read_file": "📖",
                     "edit_file": "✏️", "patch_file": "✏️", "verify_file": "🔍",
                     "search_files": "🔍", "run_skill": "🚀",
                     "rag_query": "🔎", "rag_index": "📚",
                     "search_web": "🌐", "remember": "💾",
                     "save_experience": "💾", "final": "✅"}.get(kind, "➡️")
            if kind == "shell":
                cmd = str(action.get("command", ""))[:200]
                self._status(f"{emoji} Step {self._step}: {escape_html(cmd)}")
            elif kind == "final":
                msg = str(action.get("message", ""))[:200]
                self._status(f"✅ {escape_html(msg)}", edit=False)
                send_html(self.token, self.chat_id, f"<b>✅ Done</b>: {escape_html(msg)}")
            elif kind in ("write_file",):
                path = str(action.get("path", ""))
                content = str(action.get("content", ""))
                lines = content.count("\n") + 1 if content else 0
                self._status(f"{emoji} wrote {path} ({lines} lines)")
            elif kind in ("edit_file", "patch_file"):
                path = str(action.get("path", ""))
                old = str(action.get("old_str", ""))
                new = str(action.get("new_str", ""))
                added = new.count("\n") - old.count("\n")
                op = "+" if added >= 0 else ""
                self._status(f"{emoji} edit {path} ({op}{added} lines)")
            elif kind in ("read_file", "view_file"):
                path = str(action.get("path", ""))
                self._status(f"{emoji} read {path}")
            elif kind == "verify_file":
                path = str(action.get("path", ""))
                self._status(f"{emoji} verify {path}")
            elif kind == "run_skill":
                skill = str(action.get("skill", ""))
                self._status(f"{emoji} skill: {skill}")
            elif kind == "search_web":
                q = str(action.get("query", ""))
                self._status(f"{emoji} search: {escape_html(q[:100])}")
            elif kind == "rag_query":
                q = str(action.get("query", ""))
                self._status(f"{emoji} RAG: {escape_html(q[:100])}")
            elif kind == "save_experience":
                self._status(f"{emoji} saving experience")
            else:
                self._status(f"{emoji} {kind}")

        elif event == "action_finished":
            action = payload.get("action", {})
            result = str(payload.get("result", ""))
            kind = action.get("action", "")
            if result.startswith("ERROR:"):
                detail = escape_html(result[:300])
                if kind == "shell":
                    send_html(self.token, self.chat_id, f"<b>❌ Shell error</b>:\n<code>{detail}</code>")
                else:
                    send_html(self.token, self.chat_id, f"<b>❌ {kind}</b>:\n<code>{detail}</code>")
            elif kind in ("write_file", "edit_file", "patch_file"):
                detail = escape_html(result[:200])
                send_html(self.token, self.chat_id, f"<b>{'📝' if kind == 'write_file' else '✏️'} {kind}</b>\n<code>{detail}</code>")

        elif event == "final_answer":
            answer = str(payload.get("answer", ""))
            log.info("final_answer: %d chars", len(answer))
            if answer:
                send_chunked_html(self.token, self.chat_id, f"<b>✨ Result:</b>\n{escape_html(answer)}")
            else:
                send_message(self.token, self.chat_id, "✅ Task completed.")

        elif event == "plan_step_active":
            desc = str(payload.get("step_desc", ""))
            prog = str(payload.get("progress", ""))
            self._status(f"📋 {prog}: {escape_html(desc[:150])}")

        elif event == "contextualizer_starting":
            self._status("🧠 Optimizing context...")


def run_gateway(
    config_path: str | None = None,
    poll_interval: int = 1,
    single_run: bool = False,
) -> int:
    tg = TelegramConfig.load()
    if not tg:
        log.error(
            "Telegram not configured.\n"
            f"Create {TELEGRAM_CONFIG_PATH} with:\n"
            '{"token": "YOUR_BOT_TOKEN", "chat_id": "YOUR_CHAT_ID"}'
        )
        return 1

    log.info("Gateway started for %d chat(s): %s", len(tg.chat_ids), tg.chat_ids)
    last_update_id = 0

    while True:
        try:
            result = _api_request(
                tg.token, "getUpdates",
                {"offset": last_update_id + 1, "timeout": 30},
                timeout=35,
            )
        except KeyboardInterrupt:
            log.info("Gateway stopped.")
            break

        if not result:
            time.sleep(poll_interval)
            continue

        for update in result:
            update_id = int(update.get("update_id", 0))
            if update_id <= last_update_id:
                continue
            last_update_id = update_id
            msg_obj = update.get("message") or update.get("edited_message")
            if not msg_obj:
                continue
            chat_id = str(msg_obj["chat"]["id"])
            text = (msg_obj.get("text") or "").strip()
            if not text:
                continue
            if chat_id not in tg.chat_ids:
                continue

            send_action(tg.token, chat_id, "typing")

            if text == "/start":
                send_html(tg.token, chat_id,
                    "<b>🚀 Delux Gateway</b>\n\n"
                    "Run Delux — your autonomous terminal agent — from Telegram.\n\n"
                    "<b>Commands:</b>\n"
                    "/status — Check if I'm alive\n"
                    "/stats — Session stats\n"
                    "/cancel — Stop current task\n"
                    "/help — This message\n\n"
                    "<i>Just send a prompt and I'll run it.</i>")
                continue

            if text == "/help":
                send_html(tg.token, chat_id,
                    "<b>Delux Gateway Help</b>\n\n"
                    "/status — Gateway status\n"
                    "/stats — Recent session history\n"
                    "/cancel — Cancel running task\n"
                    "/reset — Reset session\n"
                    "/retry — Retry last task\n"
                    "<i>Or just send a prompt!</i>")
                continue

            if text == "/status":
                sess = get_session(chat_id)
                send_html(tg.token, chat_id,
                    f"<b>✅ Gateway running</b>\n"
                    f"• Sessions: {len(sess.history)} completed\n"
                    f"• Ready for your next task")
                continue

            if text == "/reset":
                with _session_lock:
                    _session_store[chat_id] = GatewaySession(chat_id=chat_id)
                send_message(tg.token, chat_id, "🔄 Session reset.")
                continue

            if text == "/retry":
                sess = get_session(chat_id)
                if sess.history:
                    last_task = sess.history[-1]["user"]
                    _process_prompt(tg, chat_id, last_task)
                else:
                    send_message(tg.token, chat_id, "No previous task to retry.")
                continue

            if text == "/stats":
                sess = get_session(chat_id)
                lines = ["<b>📊 Session stats</b>"]
                if sess.history:
                    for i, turn in enumerate(sess.history[-5:], 1):
                        u = escape_html(turn["user"][:80])
                        lines.append(f"  {i}. <code>{u}</code> → done")
                else:
                    lines.append("  No tasks yet.")
                send_html(tg.token, chat_id, "\n".join(lines))
                continue

            if text == "/cancel":
                if _cancel_current():
                    send_message(tg.token, chat_id, "❌ Task cancelled.")
                else:
                    send_message(tg.token, chat_id, "No active task to cancel.")
                continue

            _process_prompt(tg, chat_id, text)
            if single_run:
                break

    return 0


def _process_prompt(tg: TelegramConfig, chat_id: str, text: str) -> None:
    cancel_ev = _register_task()
    session = get_session(chat_id)
    send_html(tg.token, chat_id, f"<i>Processing...</i>\n{escape_html(text[:200])}")

    try:
        handler = GatewayEventHandler(tg.token, chat_id, session)
        handler.set_cancel_flag(cancel_ev)

        from ..agent import Agent
        from ..config import load_config
        delux_home = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
        config = load_config(delux_home)
        cwd_path = Path(os.getcwd()).expanduser().resolve()

        # Build session_context from history for cache-friendly prefix reuse
        session_ctx = []
        if session.history:
            for turn in session.history[-3:]:
                session_ctx.append({"role": "user", "content": turn["user"]})
                session_ctx.append({"role": "assistant", "content": turn["assistant"]})

        agent = Agent(config=config, cwd=cwd_path, event_handler=handler, max_steps=12)

        result_container: list[str] = []
        def _run_agent():
            result = agent.run_with_result(text, session_context=session_ctx if session_ctx else None)
            result_container.append(result.answer)
        run_thread = threading.Thread(target=_run_agent, daemon=True)
        run_thread.start()

        start = time.time()
        typing_sent = time.time()
        long_warned = False

        while run_thread.is_alive():
            if cancel_ev.wait(timeout=1):
                send_message(tg.token, chat_id, "❌ Task interrupted.")
                break
            now = time.time()
            if now - typing_sent > 5:
                send_action(tg.token, chat_id, "typing")
                typing_sent = now
            if now - start > 120 and not long_warned:
                long_warned = True
                send_message(tg.token, chat_id, "⏳ Task still running... I'll notify when done.")

        run_thread.join(timeout=5)
        answer = result_container[0] if result_container else ""
        if answer:
            session.add_turn(text, answer)

    except Exception as exc:
        log.error("Task error: %s", exc)
        send_html(tg.token, chat_id, f"<b>❌ Error</b>: {escape_html(str(exc)[:400])}")
    finally:
        _unregister_task()


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="delux-gateway", description="Delux Agent Telegram Gateway")
    parser.add_argument("--home", default=None, help="DELUX_HOME workspace")
    parser.add_argument("--poll-interval", type=int, default=1, help="Poll interval (seconds)")
    parser.add_argument("--once", action="store_true", help="Process one message and exit")
    args = parser.parse_args()
    return run_gateway(config_path=args.home, poll_interval=args.poll_interval, single_run=args.once)


if __name__ == "__main__":
    sys.exit(main())
