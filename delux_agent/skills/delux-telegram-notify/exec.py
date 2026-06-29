#!/usr/bin/env python3
"""Telegram notification — production-grade JSON output."""
import json
import os
import re
import sys
import ssl
import urllib.request
import urllib.parse
import urllib.error

_CONFIG_PATH = os.path.expanduser("~/.delux/telegram.json")
_MAX_MESSAGE_LENGTH = 4096
_TIMEOUT = 15


def _validate_token(token):
    if not token or not isinstance(token, str):
        return False
    return bool(re.match(r"^\d{8,12}:[A-Za-z0-9_\-]{35,}$", token))


def _validate_chat_id(chat_id):
    if chat_id is None:
        return False
    if isinstance(chat_id, (int, float)):
        return True
    if isinstance(chat_id, str) and re.match(r"^@?[\w_]+$|^-?\d+$", str(chat_id)):
        return True
    return False


def send_telegram(message):
    if not message or not isinstance(message, str) or not message.strip():
        return {"status": "error", "error": "message is empty"}

    if len(message) > _MAX_MESSAGE_LENGTH:
        return {"status": "error", "error": f"message too long ({len(message)} > {_MAX_MESSAGE_LENGTH} chars)"}

    # Load config
    if not os.path.exists(_CONFIG_PATH):
        return {"status": "error",
                "error": f"config not found at {_CONFIG_PATH}",
                "help": "create ~/.delux/telegram.json with {\"token\":\"...\",\"chat_id\":\"...\"}"}

    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
        if not raw.strip():
            return {"status": "error", "error": "config file is empty"}
        config = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"status": "error", "error": f"invalid JSON in config: {exc}"}
    except PermissionError:
        return {"status": "error", "error": f"permission denied reading {_CONFIG_PATH}"}
    except (UnicodeDecodeError, OSError) as exc:
        return {"status": "error", "error": f"cannot read config: {exc}"}

    if not isinstance(config, dict):
        return {"status": "error", "error": "config must be a JSON object"}

    token = config.get("token")
    chat_id = config.get("chat_id")

    if not token:
        return {"status": "error", "error": "missing 'token' in config"}
    if not _validate_token(token):
        return {"status": "error", "error": "invalid token format"}
    if not chat_id:
        return {"status": "error", "error": "missing 'chat_id' in config"}
    if not _validate_chat_id(chat_id):
        return {"status": "error", "error": "invalid chat_id format"}

    text = f"\\U0001F916 *Delux Agent Update:*\\n\\n{message}"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        data_bytes = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")

        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            http_code = resp.getcode()

        try:
            api_resp = json.loads(body)
        except json.JSONDecodeError:
            return {"status": "error", "error": f"non-JSON API response (HTTP {http_code})",
                    "raw": body[:500]}

        if api_resp.get("ok"):
            return {"status": "ok", "data": {"message_id": api_resp["result"].get("message_id"),
                                              "chat": api_resp["result"].get("chat", {}).get("username")}}
        return {"status": "error", "error": api_resp.get("description", "unknown API error"),
                "error_code": api_resp.get("error_code"), "http_code": http_code}

    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
            detail = json.loads(body).get("description", str(exc))
        except Exception:
            detail = str(exc)
        return {"status": "error", "error": f"HTTP {exc.code}: {detail}", "http_code": exc.code}

    except urllib.error.URLError as exc:
        reason = str(exc.reason)
        if "timeout" in reason.lower() or "timed out" in reason.lower():
            return {"status": "error", "error": "network timeout"}
        return {"status": "error", "error": f"network error: {reason}"}

    except ssl.SSLError as exc:
        return {"status": "error", "error": f"SSL error: {exc}"}

    except OSError as exc:
        return {"status": "error", "error": f"OS error: {exc}"}

    except Exception as exc:
        return {"status": "error", "error": f"unexpected error: {exc}"}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"status": "error",
                          "error": "usage: delux-telegram-notify <message>",
                          "help": "Provide a message string as argument(s)"}))
        sys.exit(1)

    message = " ".join(sys.argv[1:]).strip()
    result = send_telegram(message)
    print(json.dumps(result))
    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
