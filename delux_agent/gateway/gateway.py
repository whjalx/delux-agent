from __future__ import annotations

import json
import logging
import os
import random
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

TELEGRAM_CONFIG_PATH = os.path.expanduser("~/.delux/telegram.json")
MAX_MESSAGE_LENGTH = 4000
MAX_REPORT_LENGTH = 3800
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


def truncate(text: str, max_len: int = 300) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len-3] + "..."


def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def fmt_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s"


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
            if "message is not modified" in desc:
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
    return _send_raw(token, chat_id, escape_html(text), parse_mode="", **kwargs)


def send_html(token: str, chat_id: str, html_text: str, **kwargs) -> int | None:
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


def edit_html(token: str, chat_id: str, message_id: int, html_text: str, reply_markup: dict | None = None) -> bool:
    return edit_message(token, chat_id, message_id, html_text, parse_mode="HTML", reply_markup=reply_markup)


def delete_message(token: str, chat_id: str, message_id: int) -> None:
    _api_request(token, "deleteMessage", {"chat_id": chat_id, "message_id": message_id})


def send_action(token: str, chat_id: str, action: str) -> None:
    _api_request(token, "sendChatAction", {"chat_id": chat_id, "action": action})


def answer_callback_query(token: str, callback_query_id: str, text: str = "", show_alert: bool = False) -> None:
    _api_request(token, "answerCallbackQuery", {
        "callback_query_id": callback_query_id,
        "text": text,
        "show_alert": show_alert,
    })


DIVIDER = "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"


def _diff_lines(old: str, new: str, max_lines: int = 12) -> list[tuple[str, str]]:
    import difflib
    old_l = old.split("\n")
    new_l = new.split("\n")
    diff = list(difflib.unified_diff(old_l, new_l, lineterm=""))
    if len(diff) >= 2:
        diff = diff[2:]
    result: list[tuple[str, str]] = []
    for line in diff[:max_lines]:
        if line.startswith("+"):
            result.append(("+", line[1:]))
        elif line.startswith("-"):
            result.append(("-", line[1:]))
        elif line.startswith("@@"):
            result.append(("@", line))
        else:
            result.append((" ", line[1:] if line.startswith(" ") else line))
    if len(diff) > max_lines:
        result.append(("...", f"({len(diff) - max_lines} more lines)"))
    return result


def _get_builtin_dir() -> Path:
    import delux_agent
    return Path(delux_agent.__file__).parent / "skills"


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
    plan_mode: bool = False
    ask_mode: bool = False
    ephemeral: bool = False
    validate_mode: str = "off"
    session_summary: str = ""
    cwd: str = ""
    active_model_idx: int = 0
    validator_model_idx: int | None = None
    lang: str = "en"
    max_steps: int = 90
    _awaiting_pending: str = ""  # pending task prompt awaiting user confirmation

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


# ── Beautiful Report Builder ──

_ACTION_ICONS = {
    "shell": "\U0001f4bb",
    "shell_secure": "\U0001f6e1\ufe0f",
    "write_file": "\U0001f4dd",
    "edit_file": "\u270f\ufe0f",
    "patch_file": "\u270f\ufe0f",
    "read_file": "\U0001f4d6",
    "view_file": "\U0001f4d6",
    "verify_file": "\U0001f50d",
    "append_file": "\U0001f4dd",
    "move_file": "\U0001f4c2",
    "search_files": "\U0001f50e",
    "search_web": "\U0001f310",
    "run_skill": "\U0001f680",
    "create_skill": "\U0001f4a1",
    "record_skill": "\U0001f4cb",
    "rag_query": "\U0001f50e",
    "rag_index": "\U0001f4da",
    "save_experience": "\U0001f4be",
    "remember": "\U0001f4be",
    "call_mcp": "\U0001f916",
    "browser_navigate": "\U0001f310",
    "browser_click": "\U0001f446",
    "browser_type": "\U0001f5a5\ufe0f",
    "browser_snapshot": "\U0001f4f7",
    "browser_scroll": "\U0001f5c3\ufe0f",
    "browser_screenshot": "\U0001f4f7",
    "browser_extract": "\U0001f4cb",
    "set_tasks": "\U0001f4cb",
    "task_done": "\u2705",
    "final": "\u2705",
    "skip_step": "\u23ed\ufe0f",
    "cron_add": "\u23f0",
    "cron_list": "\U0001f4cb",
    "cron_remove": "\u274c",
    "cron_run": "\u25b6\ufe0f",
    "kanban_add": "\U0001f4cb",
    "kanban_list": "\U0001f4cb",
    "kanban_move": "\U0001f4c2",
    "kanban_delete": "\u274c",
    "computer_screenshot": "\U0001f4f7",
    "computer_click": "\U0001f446",
    "computer_type": "\U0001f5a5\ufe0f",
    "computer_keypress": "\u2328\ufe0f",
}


def _fmt_action(action: dict) -> str:
    kind = action.get("action", "")
    icon = _ACTION_ICONS.get(kind, "\u27a1\ufe0f")
    if kind == "shell":
        cmd = str(action.get("command", ""))[:300]
        return f'{icon} <code>$ {escape_html(cmd)}</code>'
    if kind == "shell_secure":
        cmd = str(action.get("command", ""))[:300]
        return f'{icon} <code>$ {escape_html(cmd)}</code> <i>(safe)</i>'
    if kind in ("write_file", "append_file"):
        path = str(action.get("path", ""))
        content = str(action.get("content", ""))
        lines = content.count("\n") + 1 if content else 0
        return f'{icon} <code>{escape_html(path)}</code> <i>({lines} lines)</i>'
    if kind == "edit_file":
        path = str(action.get("path", ""))
        old = str(action.get("old_str", ""))
        new = str(action.get("new_str", ""))
        delta = new.count("\n") - old.count("\n")
        sign = "+" if delta >= 0 else ""
        return f'{icon} <code>{escape_html(path)}</code> <i>({sign}{delta} lines)</i>'
    if kind == "patch_file":
        return f'{icon} <code>{escape_html(str(action.get("path", "")))}</code>'
    if kind in ("read_file", "view_file", "verify_file"):
        return f'{icon} <code>{escape_html(str(action.get("path", "")))}</code>'
    if kind == "move_file":
        src = str(action.get("src", ""))
        dst = str(action.get("dst", ""))
        return f'{icon} <code>{escape_html(src)}</code> \u2192 <code>{escape_html(dst)}</code>'
    if kind in ("search_files", "rag_query"):
        return f'{icon} <code>{escape_html(str(action.get("query", ""))[:100])}</code>'
    if kind == "search_web":
        return f'{icon} <code>{escape_html(str(action.get("query", ""))[:100])}</code>'
    if kind == "run_skill":
        skill = str(action.get("skill", ""))
        args = str(action.get("args", ""))[:80]
        s = f'{icon} <code>{escape_html(skill)}</code>'
        if args:
            s += f' <i>{escape_html(args)}</i>'
        return s
    if kind in ("create_skill", "record_skill"):
        return f'{icon} <code>{escape_html(str(action.get("name", "")))}</code>'
    if kind == "call_mcp":
        server = str(action.get("server", ""))
        tool = str(action.get("tool", ""))
        return f'{icon} {escape_html(server)}.<code>{escape_html(tool)}</code>'
    if kind == "set_tasks":
        raw = action.get("tasks", "")
        n = len(raw) if isinstance(raw, list) else (raw.count(",") + 1 if raw else 0)
        return f'{icon} {n} tasks'
    if kind == "task_done":
        desc = str(action.get("task", ""))[:80]
        return f'{icon} <code>{escape_html(desc)}</code>'
    if kind == "final":
        return f'{icon} {escape_html(str(action.get("message", ""))[:200])}'
    if kind == "skip_step":
        sid = action.get("step_id", "")
        reason = str(action.get("reason", ""))[:100]
        return f'{icon} step {sid}: <i>{escape_html(reason)}</i>'
    name = str(action.get("name", "") or action.get("path", "") or action.get("command", "") or kind)
    return f'{icon} <code>{escape_html(name[:100])}</code>'


def _fmt_result(result: str, max_len: int = 400) -> str:
    if not result:
        return ""
    if result.startswith("SUCCESS:"):
        detail = result[8:].strip()
        if detail:
            return f'\u2705 <code>{escape_html(truncate(detail, max_len))}</code>'
        return '\u2705 <i>ok</i>'
    if result.startswith("ERROR:"):
        detail = result[6:].strip()
        return f'\u274c <code>{escape_html(truncate(detail, max_len))}</code>'
    if result.startswith("BLOCKED:"):
        detail = result[8:].strip()
        return f'\U0001f6ab <code>{escape_html(truncate(detail, max_len))}</code>'
    return f'\U0001f4ac <code>{escape_html(truncate(result, max_len))}</code>'


# ── Event Handler ──

class GatewayEventHandler:
    def __init__(self, token: str, chat_id: str, session: GatewaySession, model_name: str = ""):
        self.token = token
        self.chat_id = chat_id
        self.session = session
        self.model_name = model_name or "delux"
        self._step = 0
        self._cancel_flag: threading.Event | None = None

        # Report state
        self._report_msg_id: int | None = None
        self._task_prompt: str = ""
        self._plan_summary: str = ""
        self._plan_steps: list[dict] = []
        self._actions: list[dict] = []
        self._action_results: list[str] = []
        self._current_action: dict | None = None
        self._current_action_result: str = ""
        self._shell_buffer: str = ""
        self._shell_truncated: bool = False
        self._current_diff: list[tuple[str, str]] = []
        self._final_answer: str = ""
        self._contextualizing: bool = False
        self._start_time: float = 0.0
        self._has_plan: bool = False
        self._tasks: list[dict] = []

    def set_cancel_flag(self, ev: threading.Event) -> None:
        self._cancel_flag = ev

    def _send_initial(self, prompt: str) -> None:
        self._task_prompt = prompt
        self._start_time = time.time()
        html = (
            f"<b>\U0001f916 Delux Agent</b>  \u00b7  "
            f"<i>{escape_html(self.model_name)}</i>\n"
            f"<code>{escape_html(prompt[:300])}</code>\n"
            f"\n<i>\u23f3 Thinking...</i>"
        )
        mid = send_html(self.token, self.chat_id, html)
        if mid:
            self._report_msg_id = mid

    def _build_report(self) -> str:
        parts = []
        total_len = 0
        elapsed = time.time() - self._start_time
        time_str = fmt_time(elapsed)
        sep = "\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"

        # ── Plan section ──
        if self._has_plan:
            plan_lines = []
            if self._plan_summary:
                plan_lines.append(f"\U0001f4cb <b>Plan:</b> {escape_html(self._plan_summary)}")
            if self._plan_steps:
                for s in self._plan_steps:
                    icon = {"completed": "\u2705", "active": "\u23f3", "pending": "\u2b1c", "failed": "\u274c"}.get(
                        s.get("status", "pending"), "\u2b1c")
                    desc = escape_html(s.get("description", f"Step {s.get('id', '?')}"))
                    plan_lines.append(f"  {icon} {desc}")
            plan_text = "\n".join(plan_lines)
            parts.append(plan_text)
            total_len += len(plan_text)

        # ── Tasks section ──
        if self._tasks:
            task_lines = []
            for t in self._tasks:
                desc = escape_html(t.get("desc", "?"))
                done = t.get("done", False)
                icon = "\u2705" if done else "\u2b1c"
                task_lines.append(f"  {icon} {desc}")
            task_text = "\n".join(task_lines)
            parts.append(task_text)
            total_len += len(task_text)

        # ── Completed actions ──
        keeps_actions = list(zip(self._actions, self._action_results))
        for _ in range(len(keeps_actions)):
            action_parts = []
            for i, (act, res) in enumerate(keeps_actions):
                step_num = i + 1
                action_parts.append(f"\u2500\u2500 <b>{step_num}</b> \u2500\u2500")
                action_parts.append(_fmt_action(act))
                if res:
                    fmt = _fmt_result(res, 180)
                    if fmt:
                        action_parts.append(f"  {fmt}")
            actions_text = "\n".join(action_parts)
            if total_len + len(actions_text) <= MAX_REPORT_LENGTH:
                parts.append(actions_text)
                total_len += len(actions_text)
                break
            keeps_actions.pop(0)

        # ── Current action ──
        if self._current_action:
            curr_parts = []
            curr_parts.append(f"\u2500\u2500 <b>{self._step}</b> \u2500\u2500 <i>running...</i>")
            curr_parts.append(_fmt_action(self._current_action))
            # Diff preview
            if self._current_diff:
                diff_lines = []
                for prefix, line in self._current_diff:
                    if prefix == "+":
                        diff_lines.append(f'<code>+ {escape_html(line)}</code>')
                    elif prefix == "-":
                        diff_lines.append(f'<code>- {escape_html(line)}</code>')
                    elif prefix == "@":
                        diff_lines.append(f'<code>  {escape_html(line)}</code>')
                    elif prefix == " ":
                        diff_lines.append(f'<code>  {escape_html(line)}</code>')
                    elif prefix == "...":
                        diff_lines.append(f'<i>  {escape_html(line)}</i>')
                curr_parts.append("\n".join(diff_lines))
            # Shell output
            if self._shell_buffer:
                shell = self._shell_buffer
                if self._shell_truncated:
                    shell = f"\u23f3 <i>{fmt_bytes(len(self._shell_buffer))} total, showing last 600 B</i>\n" + shell[-600:]
                curr_parts.append(f"<pre>{escape_html(truncate(shell, 800))}</pre>")
            # Action result
            if self._current_action_result:
                fmt = _fmt_result(self._current_action_result, 250)
                if fmt:
                    curr_parts.append(f"  {fmt}")
            curr_text = "\n".join(curr_parts)
            parts.append(curr_text)
            total_len += len(curr_text)

        # ── Contextualizing ──
        if self._contextualizing:
            ctx = "\U0001f9e0 <i>Optimizing context...</i>"
            if total_len + len(ctx) <= MAX_REPORT_LENGTH:
                parts.append(ctx)
                total_len += len(ctx)

        # ── Final answer ──
        if self._final_answer:
            final_block = []
            final_block.append(f"{sep}\n<b>\u2728 Result</b>{sep}")
            final_block.append(f"{escape_html(truncate(self._final_answer, 1500))}")
            final_text = "\n".join(final_block)
            if total_len + len(final_text) <= MAX_REPORT_LENGTH:
                parts.append(final_text)
            else:
                parts.append(f"{sep}\n<b>\u2728 Result</b> <i>(truncated)</i>{sep}")
                parts.append(escape_html(self._final_answer[:200]))

        # ── Footer ──
        total_steps = len(self._actions) + (1 if self._current_action else 0)
        footer_parts = [sep[1:]]
        meta = f"<i>{escape_html(self.model_name)}</i>"
        if total_steps:
            meta += f"  \u00b7  {total_steps} step{'s' if total_steps != 1 else ''}"
        meta += f"  \u00b7  {time_str}"
        footer_parts.append(meta)
        footer_text = "\n".join(footer_parts)
        if total_len + len(footer_text) <= MAX_REPORT_LENGTH:
            parts.append(footer_text)

        return "\n".join(parts)

    def _refresh(self, reply_markup: dict | None = None) -> None:
        if not self._report_msg_id:
            return
        html = self._build_report()
        # Auto-show Cancel button during execution
        if reply_markup is None and self._current_action and not self._final_answer:
            reply_markup = build_inline_keyboard([
                [("\u23f9\ufe0f Cancel", "cancel")],
            ])
        try:
            edit_html(self.token, self.chat_id, self._report_msg_id, html, reply_markup=reply_markup)
        except Exception:
            pass

    def __call__(self, event: str, payload: dict) -> None:
        if self._cancel_flag and self._cancel_flag.is_set():
            return

        if event == "action_started":
            self._step += 1
            self._current_action = payload.get("action", {})
            self._current_action_result = ""
            self._shell_buffer = ""
            self._shell_truncated = False
            self._current_diff = []
            # Capture diff preview for file modifications
            kind = self._current_action.get("action", "")
            if kind in ("edit_file", "patch_file"):
                old_str = str(self._current_action.get("old_str", ""))
                new_str = str(self._current_action.get("new_str", ""))
                if old_str or new_str:
                    self._current_diff = _diff_lines(old_str, new_str)
            elif kind in ("write_file", "append_file"):
                content = str(self._current_action.get("content", ""))
                if content:
                    self._current_diff = [("+", l) for l in content.split("\n")[:12]]
            self._refresh()

        elif event == "action_info":
            msg = str(payload.get("message", ""))
            if msg:
                log.info("action_info: %s", msg[:100])
            self._refresh()

        elif event == "shell_output":
            chunk = str(payload.get("chunk", ""))
            if chunk:
                self._shell_buffer += chunk
                if len(self._shell_buffer) > 2000:
                    self._shell_truncated = True
                    self._shell_buffer = self._shell_buffer[-1000:]
                self._refresh()

        elif event == "action_finished":
            action = payload.get("action", {})
            result = str(payload.get("result", ""))
            kind = action.get("action", "")
            if kind != "final":
                self._actions.append(dict(action))
                self._action_results.append(result)
                if len(self._actions) > 10:
                    self._actions.pop(0)
                    self._action_results.pop(0)
                self._current_action = None
                self._current_action_result = ""
                self._shell_buffer = ""
                self._shell_truncated = False
                self._refresh()

        elif event == "final_answer":
            answer = str(payload.get("answer", ""))
            log.info("final_answer: %d chars", len(answer))
            self._final_answer = answer
            self._current_action = None
            self._current_action_result = ""
            self._shell_buffer = ""
            self._shell_truncated = False
            self._current_diff = []
            # Show post-completion actions
            keyboard = build_inline_keyboard([
                [("\U0001f504 Retry", "retry"), ("\u270f\ufe0f Refine", "refine"), ("\U0001f9f9 New", "new")],
            ])
            self._refresh(reply_markup=keyboard)

        elif event == "cache_warming":
            part = payload.get("part", 0)
            total = payload.get("total", 0)
            if not self._report_msg_id:
                return
            edit_html(self.token, self.chat_id, self._report_msg_id,
                      f"<b>\U0001f9e0 Warming KV cache</b> \U0001f525\n"
                      f"<code>Chunk {part}/{total}</code>")

        elif event == "cache_warmed":
            if self._report_msg_id:
                edit_html(self.token, self.chat_id, self._report_msg_id,
                          f"<b>\u2705 KV cache ready</b>\n\U0001f914 Thinking...")

        elif event == "plan_step_active":
            step_id = payload.get("step_id", "")
            step_desc = str(payload.get("step_desc", ""))
            progress = str(payload.get("progress", ""))
            self._has_plan = True
            # Update or add plan step
            found = False
            for s in self._plan_steps:
                if str(s.get("id", "")) == str(step_id):
                    s["status"] = "active"
                    s["description"] = step_desc
                    found = True
                    break
            if not found:
                self._plan_steps.append({"id": step_id, "description": step_desc, "status": "active"})
            self._refresh()

        elif event == "plan_step_matched":
            step_desc = str(payload.get("step_desc", ""))
            # Already handled, skip refresh noise

        elif event == "plan_step_skipped":
            step_id = payload.get("step_id", "")
            reason = str(payload.get("reason", ""))
            for s in self._plan_steps:
                if str(s.get("id", "")) == str(step_id):
                    s["status"] = "skipped"
                    s["reason"] = reason
                    break
            self._refresh()

        elif event == "plan_step_status":
            step_id = payload.get("step_id", "")
            ok = payload.get("ok", False)
            for s in self._plan_steps:
                if str(s.get("id", "")) == str(step_id):
                    s["status"] = "completed" if ok else "failed"
                    break
            self._refresh()

        elif event == "plan_completed":
            summary = payload.get("summary", "")
            self._plan_summary = summary
            self._refresh()

        elif event == "plan_final_blocked":
            pass

        elif event == "plan_max_steps_reached":
            summary = payload.get("summary", "")
            max_steps_line = f"\u26a0\ufe0f Max steps reached"
            if summary:
                max_steps_line += f": {escape_html(summary)}"
            if self._report_msg_id:
                self._final_answer = max_steps_line
                self._refresh()

        elif event == "contextualizer_starting":
            self._contextualizing = True
            self._refresh()

        elif event == "contextualizer_finished":
            self._contextualizing = False
            self._refresh()

        elif event == "tasks_updated":
            self._tasks = payload.get("tasks", [])
            self._refresh()


# ── Command Dispatch ──

COMMANDS: dict[str, tuple[str, str]] = {
    "/start": ("start", "Welcome message"),
    "/help": ("help", "Show help"),
    "/status": ("status", "Check gateway status"),
    "/stats": ("stats", "Session stats"),
    "/cancel": ("cancel", "Cancel running task"),
    "/reset": ("reset", "Reset session"),
    "/retry": ("retry", "Retry last task"),
    "/plan": ("plan", "Toggle plan mode [on|off]"),
    "/p": ("plan", "Alias for /plan"),
    "/ephemeral": ("ephemeral", "Toggle ephemeral mode [on|off]"),
    "/e": ("ephemeral", "Alias for /ephemeral"),
    "/ask": ("ask", "Toggle ask mode [on|off]"),
    "/a": ("ask", "Alias for /ask"),
    "/model": ("model", "List/switch models [N|add ...]"),
    "/vm": ("vm", "Validator model [N|off]"),
    "/template": ("template", "Show/set templates"),
    "/train": ("train", "Feedback examples [stats|list|clear|export]"),
    "/compact": ("compact", "Compress conversation"),
    "/pwd": ("pwd", "Show working directory"),
    "/cd": ("cd", "Change directory"),
    "/context": ("context", "Show memory, skills, docs"),
    "/memory": ("memory", "Show memory"),
    "/skills": ("skills", "List skills"),
    "/docs": ("docs", "Show docs"),
    "/config": ("config", "Show config"),
    "/lang": ("lang", "Change language [en|es]"),
    "/history": ("history", "Show recent prompts"),
    "/validate": ("validate", "Toggle validation [on|off|once]"),
    "/v": ("validate", "Alias for /validate"),
    "/new-skill": ("new_skill", "Create a new skill"),
    "/save": ("save", "Save session checkpoint"),
    "/sessions": ("sessions", "Show session info"),
    "/max-steps": ("max_steps", "Set max steps [N]"),
}


def handle_command(tg: TelegramConfig, chat_id: str, text: str, session: GatewaySession) -> str | None:
    """Handle a /command. Returns HTML response or None if not a command."""
    if not text.startswith("/"):
        return None

    parts = text.split()
    cmd = parts[0].lower()
    args = parts[1:]

    handler_map = {
        "start": _cmd_start, "help": _cmd_help,
        "status": _cmd_status, "stats": _cmd_stats,
        "cancel": _cmd_cancel, "reset": _cmd_reset, "retry": _cmd_retry,
        "plan": _cmd_plan, "ephemeral": _cmd_ephemeral, "ask": _cmd_ask,
        "model": _cmd_model, "vm": _cmd_vm,
        "template": _cmd_template, "train": _cmd_train,
        "compact": _cmd_compact,
        "pwd": _cmd_pwd, "cd": _cmd_cd,
        "context": _cmd_context, "memory": _cmd_memory,
        "skills": _cmd_skills, "docs": _cmd_docs,
        "config": _cmd_config, "lang": _cmd_lang,
        "history": _cmd_history, "validate": _cmd_validate,
        "new_skill": _cmd_new_skill, "save": _cmd_save,
        "sessions": _cmd_sessions, "max_steps": _cmd_max_steps,
    }

    handler = handler_map.get(COMMANDS.get(cmd, [None])[0] if cmd in COMMANDS else None)
    if handler is None:
        # Check by alias
        for full_cmd, (h, _) in COMMANDS.items():
            if full_cmd == cmd:
                handler = handler_map.get(h)
                break
    if handler is None:
        return f"<b>\u2753 Unknown command</b>: <code>{escape_html(cmd)}</code>\n/help for available commands."

    try:
        return handler(tg, chat_id, args, session)
    except Exception as e:
        log.error("Command error %s: %s", cmd, e)
        return f"<b>\u274c Error</b>: {escape_html(str(e)[:300])}"


def _cmd_start(tg, chat_id, args, session) -> str:
    return (
        "<b>\U0001f680 Delux Gateway</b>\n\n"
        "Your autonomous terminal agent, now on Telegram.\n\n"
        "Send me any task and I'll execute it via shell commands, "
        "file operations, and more.\n\n"
        "<b>Commands:</b>\n"
        "\U0001f4cb <code>/plan on</code> \u2014 Create a plan before executing\n"
        "\U0001f4ca <code>/stats</code> \u2014 Session activity\n"
        "\U0001f504 <code>/retry</code> \u2014 Repeat last task\n"
        "\u274c <code>/cancel</code> \u2014 Stop current task\n"
        "\U0001f4ac <code>/help</code> \u2014 Full command list\n\n"
        "<i>Just type what you need and I'll handle it.</i>"
    )


def _cmd_help(tg, chat_id, args, session) -> str:
    lines = ["<b>\U0001f4ac Delux Commands</b>\n"]
    cats = [
        ("\u2699\ufe0f <b>Execution</b>", ["/plan [on|off]", "/ephemeral [on|off]", "/ask [on|off]", "/validate [on|off|once]"]),
        ("\U0001f4ca <b>Info</b>", ["/status", "/stats", "/history", "/context", "/memory", "/skills", "/docs", "/config", "/pwd"]),
        ("\U0001f4dd <b>Manage</b>", ["/model [N|add ...]", "/vm [N|off]", "/template [model]", "/lang [en|es]", "/cd &lt;path&gt;", "/new-skill &lt;name&gt;", "/max-steps [N]"]),
        ("\U0001f504 <b>Session</b>", ["/retry", "/reset", "/save", "/sessions", "/compact", "/train [stats|list|clear|export]", "/cancel"]),
    ]
    for title, cmds in cats:
        lines.append(f"  {title}")
        for c in cmds:
            lines.append(f"    <code>{escape_html(c)}</code>")
        lines.append("")
    lines.append("<i>Or just send a prompt to run a task!</i>")
    return "\n".join(lines)


def _cmd_status(tg, chat_id, args, session) -> str:
    config = _load_delux_config()
    model = config.model or "deepseek"
    provider = (config.provider or "openai").upper()
    return (
        f"<b>\u2705 Gateway Running</b>\n"
        f"\U0001f5a5 Model: <code>{escape_html(model)}</code> ({escape_html(provider)})\n"
        f"\U0001f4ca Tasks: {len(session.history)} completed\n"
        f"\U0001f4cb Plan: {'ON' if session.plan_mode else 'OFF'}\n"
        f"\U0001f4ac Lang: {session.lang}\n"
        f"\U0001f4c1 CWD: <code>{escape_html(session.cwd or os.getcwd())}</code>\n"
        f"\U0001f9e0 Summary: {'yes' if session.session_summary else 'no'}"
    )


def _cmd_stats(tg, chat_id, args, session) -> str:
    if not session.history:
        return "<b>\U0001f4ca Stats</b>\n  No tasks yet."
    lines = ["<b>\U0001f4ca Recent tasks</b>"]
    for i, turn in enumerate(session.history[-5:], 1):
        u = escape_html(turn["user"][:80])
        a_preview = escape_html(turn["assistant"][:100])
        lines.append(f"  {i}. <code>{u}</code>")
        lines.append(f"     \u2192 <i>{a_preview}</i>")
    return "\n".join(lines)


def _cmd_cancel(tg, chat_id, args, session) -> str:
    if _cancel_current():
        return "\u274c Task cancelled."
    return "No active task to cancel."


def _cmd_reset(tg, chat_id, args, session) -> str:
    with _session_lock:
        _session_store[chat_id] = GatewaySession(chat_id=chat_id)
    return "\U0001f504 Session reset."


def _cmd_retry(tg, chat_id, args, session) -> str:
    if not session.history:
        return "No previous task to retry."
    # Return special string that tells run_gateway to reprocess
    return f"__RETRY__:{session.history[-1]['user']}"


def _cmd_plan(tg, chat_id, args, session) -> str:
    if not args:
        session.plan_mode = not session.plan_mode
    elif args[0] == "on":
        session.plan_mode = True
    elif args[0] == "off":
        session.plan_mode = False
    else:
        return "Usage: <code>/plan [on|off]</code>"
    state = "ON" if session.plan_mode else "OFF"
    return f"\U0001f4cb Plan mode: <b>{state}</b>"


def _cmd_ephemeral(tg, chat_id, args, session) -> str:
    if not args:
        session.ephemeral = not session.ephemeral
    elif args[0] == "on":
        session.ephemeral = True
    elif args[0] == "off":
        session.ephemeral = False
    else:
        return "Usage: <code>/ephemeral [on|off]</code>"
    state = "ON" if session.ephemeral else "OFF"
    return f"\U0001f4dd Ephemeral: <b>{state}</b>"


def _cmd_ask(tg, chat_id, args, session) -> str:
    if not args:
        session.ask_mode = not session.ask_mode
    elif args[0] == "on":
        session.ask_mode = True
    elif args[0] == "off":
        session.ask_mode = False
    else:
        return "Usage: <code>/ask [on|off]</code>"
    state = "ON" if session.ask_mode else "OFF"
    return f"\U0001f4ac Ask mode: <b>{state}</b>"


def _cmd_validate(tg, chat_id, args, session) -> str:
    if not args:
        session.validate_mode = "on" if session.validate_mode == "off" else "off"
    elif args[0] in ("on", "off", "once"):
        session.validate_mode = args[0]
    else:
        return "Usage: <code>/validate [on|off|once]</code>"
    return f"\U0001f50d Validate: <b>{session.validate_mode.upper()}</b>"


def _cmd_model(tg, chat_id, args, session) -> str:
    config = _load_delux_config()
    if not args:
        lines = ["<b>\U0001f5a5 Models</b>"]
        for i, m in enumerate(config.models):
            mark = " \u2190 active" if i == session.active_model_idx else ""
            lines.append(f"  {i}. <code>{escape_html(m.name)}</code>{mark}")
        lines.append("")
        lines.append("Usage: <code>/model &lt;N&gt;</code> or <code>/model add &lt;name&gt; &lt;provider&gt; [api_base]</code>")
        return "\n".join(lines)
    try:
        idx = int(args[0])
        if 0 <= idx < len(config.models):
            session.active_model_idx = idx
            return f"\U0001f5a5 Active model: <b>{escape_html(config.models[idx].name)}</b>"
        return f"Invalid index: {idx}"
    except ValueError:
        pass
    if args[0] == "add" and len(args) >= 3:
        from ..config import ModelEntry
        name = args[1]
        provider = args[2]
        api_base = args[3] if len(args) > 3 else ""
        config.models.append(ModelEntry(name=name, provider=provider, api_base=api_base))
        return f"\U0001f5a5 Added model: <b>{escape_html(name)}</b> ({escape_html(provider)})"
    return "Usage: <code>/model &lt;N&gt;</code> or <code>/model add &lt;name&gt; &lt;provider&gt; [api_base]</code>"


def _cmd_vm(tg, chat_id, args, session) -> str:
    config = _load_delux_config()
    if not args:
        if session.validator_model_idx is not None:
            m = config.models[session.validator_model_idx]
            return f"\U0001f50d Validator: <b>{escape_html(m.name)}</b>"
        return "Validator: same as active model"
    if args[0] == "off":
        session.validator_model_idx = None
        return "\U0001f50d Validator: same as active model"
    try:
        idx = int(args[0])
        if 0 <= idx < len(config.models):
            session.validator_model_idx = idx
            return f"\U0001f50d Validator: <b>{escape_html(config.models[idx].name)}</b>"
        return f"Invalid index: {idx}"
    except ValueError:
        return "Usage: <code>/vm &lt;N&gt;</code> or <code>/vm off</code>"


def _cmd_template(tg, chat_id, args, session) -> str:
    from ..templates import list_templates, get_model_template, set_template
    config = _load_delux_config()
    root = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))

    if not args:
        templates = list_templates(root)
        if not templates:
            return "No templates configured."
        lines = ["<b>\U0001f4cb Templates</b>"]
        for name, t in templates:
            suffix = t.system_suffix[:60] if t.system_suffix else "\u2014"
            lines.append(f"  <code>{escape_html(name)}</code> \u2192 {escape_html(t.preferred_strategy)}")
            lines.append(f"    suffix: <i>{escape_html(suffix)}</i>")
        return "\n".join(lines)

    model = args[0]
    if len(args) == 1:
        t = get_model_template(model, root)
        suffix = t.system_suffix if t.system_suffix else "\u2014"
        return (
            f"<b>\U0001f4cb {escape_html(model)}</b>\n"
            f"  Strategy: <code>{escape_html(t.preferred_strategy)}</code>\n"
            f"  Suffix: <i>{escape_html(suffix)}</i>"
        )

    if len(args) >= 3 and args[1] == "strategy":
        set_template(model, strategy=args[2], root=root)
        return f"\U0001f4cb {escape_html(model)} strategy = <code>{escape_html(args[2])}</code>"

    if len(args) >= 3 and args[1] == "suffix":
        suffix = " ".join(args[2:])
        set_template(model, suffix=suffix, root=root)
        return f"\U0001f4cb {escape_html(model)} suffix updated."

    return "Usage: <code>/template [model]</code> | <code>/template &lt;model&gt; strategy &lt;s&gt;</code> | <code>/template &lt;model&gt; suffix \"text\"</code>"


def _cmd_train(tg, chat_id, args, session) -> str:
    root = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
    examples_path = root / "examples" / "feedback.jsonl"
    if not args:
        total = 0
        if examples_path.exists():
            with open(examples_path) as f:
                for line in f:
                    if line.strip():
                        total += 1
        return f"<b>\U0001f4ca Feedback examples</b>: {total}\n/stats for details, /train clear to reset."

    cmd = args[0]
    if cmd == "stats":
        if not examples_path.exists():
            return "No feedback examples."
        total = 0
        cats = {}
        with open(examples_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    data = json.loads(line)
                    m = data.get("model", "?")
                    cats[m] = cats.get(m, 0) + 1
                except json.JSONDecodeError:
                    pass
        size = examples_path.stat().st_size
        models = ", ".join(f"{m}: {c}" for m, c in sorted(cats.items(), key=lambda x: -x[1]))
        return (
            f"<b>\U0001f4ca Feedback Examples</b>\n"
            f"  Total: {total}\n"
            f"  Size: {fmt_bytes(size)}\n"
            f"  Models: {escape_html(models)}"
        )

    elif cmd == "list":
        if not examples_path.exists():
            return "No feedback examples."
        entries = []
        with open(examples_path) as f:
            for line in f:
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        entries = entries[-5:]
        lines = ["<b>\U0001f4dc Recent Examples</b>"]
        for e in reversed(entries):
            p = escape_html(e.get("prompt", "")[:60])
            ts = e.get("timestamp", "")[:10]
            lines.append(f"  <code>{p}</code> <i>{ts}</i>")
        return "\n".join(lines)

    elif cmd == "clear":
        if examples_path.exists():
            examples_path.unlink()
        return "\U0001f4dc Feedback examples cleared."

    elif cmd == "export":
        if not examples_path.exists():
            return "No examples to export."
        export_path = root / "examples" / "feedback_export.jsonl"
        import shutil
        shutil.copy2(examples_path, export_path)
        return f"\U0001f4dc Exported to <code>{escape_html(str(export_path))}</code>"

    return "Usage: <code>/train [stats|list|clear|export]</code>"


def _cmd_compact(tg, chat_id, args, session) -> str:
    if not session.history:
        return "No conversation to compress."

    config = _load_delux_config()
    model_name = config.model or "deepseek"

    lines = []
    for i, turn in enumerate(session.history, 1):
        lines.append(f"Turn {i}:")
        lines.append(f"  User: {turn['user']}")
        lines.append(f"  Assistant: {turn['assistant'][:600]}")
        lines.append("")
    full_text = "\n".join(lines)

    summary_prompt = (
        "Summarize the following conversation between a user and Delux (an AI assistant). "
        "Extract: main goals, what was accomplished, key decisions, current state, "
        "files modified, skills created. Be concise but informative.\n\n"
        + full_text
    )

    try:
        from ..llm import chat_completion
        response = chat_completion(
            config.api_base, config.api_key, model_name,
            [{"role": "user", "content": summary_prompt}],
            config.api_endpoint, timeout=30,
        )
        summary = response.text.strip()
    except Exception as e:
        summary = "Recent conversation:\n"
        for turn in session.history[-3:]:
            summary += f"User: {turn['user'][:200]}\nAss: {turn['assistant'][:200]}\n"
        summary += f"\n<small>(LLM error: {escape_html(str(e)[:100])})</small>"

    session.session_summary = summary
    session.history = []
    return (
        f"<b>\U0001f504 Conversation compacted</b>\n\n"
        f"{escape_html(summary[:600])}\n\n"
        f"<i>The summary is now used as context for future tasks.</i>"
    )


def _cmd_pwd(tg, chat_id, args, session) -> str:
    cwd = session.cwd or os.getcwd()
    return f"\U0001f4c1 <code>{escape_html(cwd)}</code>"


def _cmd_cd(tg, chat_id, args, session) -> str:
    if not args:
        return _cmd_pwd(tg, chat_id, args, session)
    try:
        new = Path(args[0]).expanduser().resolve()
        if new.is_dir():
            session.cwd = str(new)
            return f"\U0001f4c1 \u2192 <code>{escape_html(str(new))}</code>"
        return f"Not a directory: {escape_html(args[0])}"
    except Exception as e:
        return f"Error: {escape_html(str(e))}"


def _cmd_context(tg, chat_id, args, session) -> str:
    root = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
    from ..store import load_memory, load_skills, load_docs
    memory = load_memory(root / "memory" / "memory.md")[:500]
    skills = load_skills(_get_builtin_dir(), root / "skills")
    docs = load_docs(root / "docs")[:500]

    lines = ["<b>\U0001f4da Context</b>"]
    if memory.strip():
        lines.append(f"\U0001f4ac <b>Memory</b>: {escape_html(memory.strip()[:200])}")
    else:
        lines.append("\U0001f4ac Memory: empty")
    if skills:
        skill_list = ", ".join(f"<code>{s.name}</code>" for s in skills[:5])
        lines.append(f"\U0001f4e6 <b>Skills</b> ({len(skills)}): {skill_list}")
    else:
        lines.append("\U0001f4e6 Skills: none")
    if docs.strip():
        lines.append(f"\U0001f4c4 <b>Docs</b>: <code>{escape_html(truncate(docs.strip(), 200))}</code>")
    else:
        lines.append("\U0001f4c4 Docs: none")
    return "\n".join(lines)


def _cmd_memory(tg, chat_id, args, session) -> str:
    root = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
    from ..store import load_memory
    memory = load_memory(root / "memory" / "memory.md")
    if not memory.strip():
        return "\U0001f4ac Memory: empty."
    return f"<b>\U0001f4ac Memory</b>:\n{escape_html(memory.strip()[:1500])}"


def _cmd_skills(tg, chat_id, args, session) -> str:
    root = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
    from ..store import load_skills
    skills = load_skills(_get_builtin_dir(), root / "skills")
    if not skills:
        return "No skills installed."
    lines = [f"<b>\U0001f4e6 Skills ({len(skills)})</b>"]
    for s in skills:
        badge = f" [exec:{s.exec_lang}]" if s.has_exec else ""
        lines.append(f"  \u2022 <code>{escape_html(s.name)}{badge}</code>: {escape_html(s.summary[:80])}")
    return "\n".join(lines)


def _cmd_docs(tg, chat_id, args, session) -> str:
    root = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
    from ..store import load_docs
    docs = load_docs(root / "docs")[:1500]
    if not docs.strip():
        return "\U0001f4c4 No docs."
    return f"<b>\U0001f4c4 Docs</b>:\n{escape_html(docs.strip()[:1500])}"


def _cmd_config(tg, chat_id, args, session) -> str:
    root = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
    config_path = root / "config.json"
    if config_path.exists():
        content = config_path.read_text(encoding="utf-8")[:1500]
        return f"<b>\u2699\ufe0f Config</b>:\n<pre>{escape_html(content)}</pre>"
    return "Config file not found."


def _cmd_lang(tg, chat_id, args, session) -> str:
    if not args:
        return f"\U0001f4ac Language: {session.lang}"
    lang = args[0].lower()
    if lang in ("en", "es"):
        session.lang = lang
        return f"\U0001f4ac Language: {lang}"
    return "Supported: en, es"


def _cmd_history(tg, chat_id, args, session) -> str:
    if not session.history:
        return "No prompt history."
    lines = ["<b>\U0001f4dc Prompt History</b>"]
    for i, p in enumerate(session.history[-10:], 1):
        user = escape_html(p["user"][:100])
        lines.append(f"  {i}. <code>{user}</code>")
    return "\n".join(lines)


def _cmd_new_skill(tg, chat_id, args, session) -> str:
    if not args:
        return "Usage: <code>/new-skill &lt;name&gt;</code>"
    name = " ".join(args).strip()
    try:
        slug = name.lower().replace(" ", "-").replace("_", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
        root = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
        skill_dir = root / "skills" / slug
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            skill_file.write_text(
                f"# {name}\n\n"
                "Summary: \n\n"
                "## When To Use\n\n"
                "- \n\n"
                "## Steps\n\n"
                "1. \n\n"
                "## Verification\n\n"
                "- \n\n"
                "## Caveats\n\n"
                "- \n",
                encoding="utf-8",
            )
        from ..store import upsert_skill
        upsert_skill(root / "memory" / "memory.md", slug, "User-created skill.")
        return f"\U0001f4a1 Skill created: <code>{escape_html(str(skill_file))}</code>"
    except Exception as e:
        return f"Error: {escape_html(str(e)[:300])}"


def _cmd_save(tg, chat_id, args, session) -> str:
    title = " ".join(args).strip() or f"gateway-session-{chat_id}"
    try:
        root = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
        sessions_dir = root / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        lines = [f"# {title}", "", "## History"]
        for i, turn in enumerate(session.history, 1):
            lines.append(f"### Turn {i}")
            lines.append(f"User: {turn['user']}")
            lines.append(f"Assistant: {turn['assistant'][:500]}")
            lines.append("")
        path = sessions_dir / f"{title}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return f"\U0001f4be Session saved: <code>{escape_html(str(path.name))}</code>"
    except Exception as e:
        return f"Error: {escape_html(str(e)[:300])}"


def _cmd_sessions(tg, chat_id, args, session) -> str:
    lines = [f"<b>\U0001f4cb Current Session</b>"]
    lines.append(f"  Turns: {len(session.history)}")
    lines.append(f"  Plan: {'ON' if session.plan_mode else 'OFF'}")
    lines.append(f"  Max steps: {session.max_steps}")
    lines.append(f"  Summary: {'yes' if session.session_summary else 'no'}")
    if session.history:
        lines.append(f"  Last task: <code>{escape_html(session.history[-1]['user'][:80])}</code>")
    return "\n".join(lines)


def _cmd_max_steps(tg, chat_id, args, session) -> str:
    if not args:
        return f"Max steps: <b>{session.max_steps}</b>"
    try:
        n = int(args[0])
        if n < 1 or n > 100:
            return "Max steps must be between 1 and 100."
        session.max_steps = n
        return f"Max steps: <b>{n}</b>"
    except ValueError:
        return "Usage: <code>/max-steps [N]</code>"


def _load_delux_config():
    from ..config import load_config
    delux_home = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
    return load_config(delux_home)


# ── Main Gateway Loop ──

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

    from ..ddg_proxy import ensure_proxy
    from ..config import load_config as _load_delux_config
    _gw_delux_home = Path(config_path) if config_path else Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
    ensure_proxy(_load_delux_config(_gw_delux_home))

    last_update_id = 0

    while True:
        try:
            result = _api_request(
                tg.token, "getUpdates",
                {"offset": last_update_id + 1, "timeout": 5},
                timeout=10,
            )
        except KeyboardInterrupt:
            log.info("Gateway stopped.")
            break

        if result is None:
            time.sleep(poll_interval)
            continue

        for update in result:
            update_id = int(update.get("update_id", 0))
            if update_id <= last_update_id:
                continue
            last_update_id = update_id

            # ── Handle callback queries ──
            callback_query = update.get("callback_query")
            if callback_query:
                data = callback_query.get("data", "")
                cb_chat_id = str(callback_query["message"]["chat"]["id"])
                cb_msg_id = callback_query["message"]["message_id"]
                cb_id = callback_query["id"]

                if cb_chat_id not in tg.chat_ids:
                    continue

                session = get_session(cb_chat_id)

                if data == "retry":
                    answer_callback_query(tg.token, cb_id, "\U0001f504 Retrying...")
                    if session.history:
                        last_task = session.history[-1]["user"]
                        _process_prompt(tg, cb_chat_id, last_task, session)
                    else:
                        answer_callback_query(tg.token, cb_id, "No previous task.", show_alert=True)

                elif data == "refine":
                    answer_callback_query(tg.token, cb_id,
                        "Reply to this message with your refined request.")
                    delete_message(tg.token, cb_chat_id, cb_msg_id)

                elif data == "new":
                    answer_callback_query(tg.token, cb_id, "Starting fresh session.")
                    session.history.clear()
                    session.session_summary = ""
                    send_message(tg.token, cb_chat_id, "\U0001f9f9 Session reset. Send a new task.")

                else:
                    answer_callback_query(tg.token, cb_id)
                continue

            # ── Handle messages ──
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
            session = get_session(chat_id)

            # ── Handle pending task response ──
            if session._awaiting_pending:
                pending = session._awaiting_pending
                session._awaiting_pending = ""
                from ..store import clear_pending_task
                delux_home = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
                if text.lower() in ("s", "si", "y", "yes", ""):
                    clear_pending_task(delux_home)
                    send_message(tg.token, chat_id, "✅ Continuando tarea pendiente.")
                    _process_prompt(tg, chat_id, pending, session)
                else:
                    clear_pending_task(delux_home)
                    send_message(tg.token, chat_id, "❌ Tarea pendiente descartada. Envía tu nuevo prompt.")
                continue

            # ── Command handling ──
            if text.startswith("/"):
                result_html = handle_command(tg, chat_id, text, session)

                if result_html is None:
                    continue

                # Handle retry special case
                if result_html.startswith("__RETRY__:"):
                    last_task = result_html.split(":", 1)[1]
                    _process_prompt(tg, chat_id, last_task, session)
                    continue

                send_html(tg.token, chat_id, result_html)
                continue

            # ── Normal prompt ──
            _process_prompt(tg, chat_id, text, session)

            if single_run:
                break

    return 0


def _process_prompt(tg: TelegramConfig, chat_id: str, text: str, session: GatewaySession | None = None) -> None:
    cancel_ev = _register_task()
    if session is None:
        session = get_session(chat_id)

    from ..agent import prepare_agent, build_session_context
    from ..config import load_config
    from ..store import load_pending_task, clear_pending_task
    delux_home = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
    config = load_config(delux_home)
    cwd_path = Path(session.cwd).expanduser().resolve() if session.cwd else Path(os.getcwd()).expanduser().resolve()

    # ── Check for pending task from previous session ──
    pending = load_pending_task(delux_home)
    if pending:
        # Ask the user if they want to continue the pending task
        send_message(tg.token, chat_id,
                     f"📋 <b>Tarea pendiente detectada:</b>\n<code>{escape_html(pending[:300])}</code>\n\n"
                     f"❓ Envía <b>s</b> para continuar, <b>n</b> para descartar.")
        # Set a flag in the session to handle the response
        session._awaiting_pending = pending
        _unregister_task()
        return

    session_ctx = build_session_context(
        session_summary=session.session_summary,
        history=session.history,
    )

    handler = GatewayEventHandler(tg.token, chat_id, session, model_name=config.model)
    handler.set_cancel_flag(cancel_ev)
    handler._send_initial(text)

    system_suffix = (
        "[Telegram] "
        "You are Delux, running via Telegram chat. "
        "Your name is Delux. "
        "Creator: Jorge Castellano (do not mention unless asked). "
        "The user sees only your final answer as a Telegram message."
    )

    agent = prepare_agent(
        config=config,
        cwd=cwd_path,
        event_handler=handler,
        prompt=text,
        active_model_idx=session.active_model_idx,
        validator_model_idx=session.validator_model_idx,
        plan_mode=session.plan_mode,
        ephemeral=session.ephemeral,
        system_suffix=system_suffix,
        lang=session.lang,
        max_steps=session.max_steps,
    )

    result_container: list[str] = []

    def _run_agent():
        try:
            result = agent.run_with_result(text, verbose=False, session_context=session_ctx)
            result_container.append(result.answer)
        except Exception as e:
            result_container.append(f"Error: {str(e)}")

    run_thread = threading.Thread(target=_run_agent, daemon=True)
    run_thread.start()

    start = time.time()
    typing_sent = time.time()
    long_warned = False

    while run_thread.is_alive():
        if cancel_ev.wait(timeout=1):
            edit_html(tg.token, chat_id, handler._report_msg_id,
                      f"<b>\u274c Task cancelled</b>\n\n"
                      f"<code>{escape_html(text[:200])}</code>")
            send_message(tg.token, chat_id, "Interrupted.")
            break
        now = time.time()
        if now - typing_sent > 5:
            send_action(tg.token, chat_id, "typing")
            typing_sent = now
        if now - start > 120 and not long_warned:
            long_warned = True
            edit_html(tg.token, chat_id, handler._report_msg_id,
                      handler._build_report() + "\n\n<i>Still working... I'll notify when done.</i>")

    run_thread.join(timeout=5)
    answer = result_container[0] if result_container else ""
    if answer:
        session.add_turn(text, answer)
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
