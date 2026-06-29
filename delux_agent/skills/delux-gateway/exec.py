#!/usr/bin/env python3
"""Delux Gateway — Telegram to Delux Agent bridge, production-grade CLI with JSON output."""

import json
import os
import signal
import sys
import traceback

TELEGRAM_CONFIG_PATH = os.path.expanduser("~/.delux/telegram.json")

_VALID_COMMANDS = {"start", "status", "stop", "kill", "restart", "health", "help"}


def _check_config() -> dict:
    """Check if telegram.json exists and is valid. Returns status dict."""
    if not os.path.exists(TELEGRAM_CONFIG_PATH):
        return {
            "configured": False,
            "error": (
                f"Telegram config file not found at {TELEGRAM_CONFIG_PATH}. "
                "Create it with: {\"token\": \"YOUR_BOT_TOKEN\", \"chat_id\": \"YOUR_CHAT_ID\"}"
            ),
        }
    try:
        with open(TELEGRAM_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return {
            "configured": False,
            "error": f"Invalid JSON in {TELEGRAM_CONFIG_PATH}: {str(e)[:200]}",
        }
    except PermissionError:
        return {
            "configured": False,
            "error": f"Permission denied reading {TELEGRAM_CONFIG_PATH}",
        }
    except OSError as e:
        return {
            "configured": False,
            "error": f"Cannot read {TELEGRAM_CONFIG_PATH}: {str(e)[:200]}",
        }

    token = data.get("token", "").strip() if isinstance(data, dict) else ""
    raw_ids = (data.get("chat_id") or data.get("chat_ids") or []) if isinstance(data, dict) else []

    if isinstance(raw_ids, str):
        chat_ids = [raw_ids.strip()]
    elif isinstance(raw_ids, list):
        chat_ids = [str(c).strip() for c in raw_ids if str(c).strip()]
    else:
        chat_ids = []

    if not token:
        return {
            "configured": False,
            "error": "Telegram config is missing 'token' field.",
        }
    if not chat_ids:
        return {
            "configured": False,
            "error": "Telegram config is missing 'chat_id' or 'chat_ids' field (or it is empty).",
        }

    return {
        "configured": True,
        "chat_ids": chat_ids,
        "chat_count": len(chat_ids),
        "config_path": TELEGRAM_CONFIG_PATH,
        "token_preview": token[:6] + "..." + token[-4:] if len(token) > 10 else "***",
    }


def _check_module() -> dict:
    """Check if delux_agent.gateway module is importable. Returns status dict."""
    try:
        from delux_agent.gateway import run_gateway  # noqa: F401
        return {"available": True}
    except ImportError as e:
        return {
            "available": False,
            "error": (
                f"delux_agent.gateway module cannot be imported: {str(e)[:300]}. "
                "Ensure delux-agent is installed correctly. "
                "Install with: pip install delux-agent"
            ),
        }
    except Exception as e:
        return {
            "available": False,
            "error": f"Unexpected error importing delux_agent.gateway: {str(e)[:500]}",
        }


def _find_pid_file() -> str | None:
    """Find if a gateway process is running via PID file."""
    pid_file = os.path.expanduser("~/.delux/gateway.pid")
    if not os.path.exists(pid_file):
        return None
    try:
        with open(pid_file, "r") as f:
            pid_str = f.read().strip()
        return pid_str
    except Exception:
        return None


def _is_process_running(pid: str) -> bool:
    """Check if a process with the given PID is running."""
    try:
        pid_int = int(pid)
        os.kill(pid_int, 0)
        return True
    except (ValueError, OSError):
        return False


def _check_running() -> dict:
    """Check if a gateway instance is currently running."""
    pid_file = _find_pid_file()
    if pid_file is None:
        return {"running": False}
    if _is_process_running(pid_file):
        return {"running": True, "pid": int(pid_file)}
    return {"running": False, "stale_pid_file": pid_file}


def _write_pid_file() -> None:
    """Write current PID to PID file."""
    pid_file = os.path.expanduser("~/.delux/gateway.pid")
    pid_dir = os.path.dirname(pid_file)
    try:
        os.makedirs(pid_dir, exist_ok=True)
    except OSError:
        pass
    try:
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


def _stop_gateway(force: bool = False) -> dict:
    """Stop a running gateway process. Returns status dict."""
    running = _check_running()
    if not running.get("running"):
        pid_file = os.path.expanduser("~/.delux/gateway.pid")
        if os.path.exists(pid_file):
            try:
                os.remove(pid_file)
            except OSError:
                pass
        return {"action": "stop", "result": "not_running", "message": "No running gateway process found."}

    pid = running["pid"]
    sig = signal.SIGKILL if force else signal.SIGTERM
    sig_name = "SIGKILL" if force else "SIGTERM"

    try:
        os.kill(pid, sig)
    except PermissionError:
        return {
            "action": "stop",
            "result": "error",
            "message": f"Permission denied sending {sig_name} to process {pid}.",
        }
    except OSError as e:
        return {
            "action": "stop",
            "result": "error",
            "message": f"Failed to stop process {pid}: {str(e)[:200]}",
        }

    pid_file = os.path.expanduser("~/.delux/gateway.pid")
    if os.path.exists(pid_file):
        try:
            os.remove(pid_file)
        except OSError:
            pass

    return {
        "action": "stop",
        "result": "stopped",
        "message": f"Gateway process {pid} terminated with {sig_name}.",
        "pid": pid,
    }


def _start_gateway(foreground: bool = True, poll_interval: int = 1) -> dict:
    """Start the gateway. Returns status dict."""
    config_check = _check_config()
    if not config_check.get("configured"):
        return {
            "action": "start",
            "result": "error",
            "message": config_check.get("error", "Telegram not configured."),
        }

    module_check = _check_module()
    if not module_check.get("available"):
        return {
            "action": "start",
            "result": "error",
            "message": module_check.get("error", "Gateway module not available."),
        }

    running = _check_running()
    if running.get("running"):
        return {
            "action": "start",
            "result": "already_running",
            "message": f"Gateway is already running (PID {running['pid']}). Use 'stop' first.",
            "pid": running["pid"],
        }

    # Clear any stale PID file
    pid_file = os.path.expanduser("~/.delux/gateway.pid")
    if os.path.exists(pid_file):
        try:
            os.remove(pid_file)
        except OSError:
            pass

    try:
        from delux_agent.gateway import run_gateway
    except ImportError:
        return {
            "action": "start",
            "result": "error",
            "message": "Cannot import run_gateway. Install delux-agent with: pip install delux-agent",
        }

    if not foreground:
        import subprocess
        script = sys.argv[0]
        worker_dir = os.getcwd()
        try:
            subprocess.Popen(
                [sys.executable, script, "start"],
                cwd=worker_dir,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {
                "action": "start",
                "result": "daemon_started",
                "message": "Gateway started in daemon mode.",
            }
        except OSError as e:
            return {
                "action": "start",
                "result": "error",
                "message": f"Failed to start daemon: {str(e)[:200]}",
            }

    # Foreground mode
    _write_pid_file()

    def _sig_handler(signum, frame):
        pid_file = os.path.expanduser("~/.delux/gateway.pid")
        if os.path.exists(pid_file):
            try:
                os.remove(pid_file)
            except OSError:
                pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT, _sig_handler)

    try:
        exit_code = run_gateway(poll_interval=poll_interval)
        return {
            "action": "start",
            "result": "exited",
            "message": f"Gateway exited with code {exit_code}.",
            "exit_code": exit_code,
        }
    except KeyboardInterrupt:
        return {
            "action": "start",
            "result": "interrupted",
            "message": "Gateway interrupted by user.",
        }


def _gateway_health_check() -> dict:
    """Perform a health check on the gateway."""
    running = _check_running()
    config = _check_config()
    module = _check_module()

    return {
        "running": running.get("running", False),
        "pid": running.get("pid"),
        "configured": config.get("configured", False),
        "config_details": config,
        "module_available": module.get("available", False),
        "config_path": TELEGRAM_CONFIG_PATH,
        "timestamp": __import__("time").time(),
    }


def gateway_command(command: str = "status", **kwargs) -> str:
    """Main gateway entry point. Returns JSON string."""
    command = command.strip().lower() if command else "status"

    if command not in _VALID_COMMANDS:
        return json.dumps({
            "status": "error",
            "error": (
                f"Unknown command: '{command}'. "
                f"Valid commands: {', '.join(sorted(_VALID_COMMANDS))}"
            ),
        }, indent=2, ensure_ascii=False)

    try:
        if command == "status":
            running = _check_running()
            config = _check_config()
            return json.dumps({
                "status": "ok",
                "data": {
                    "running": running.get("running", False),
                    "pid": running.get("pid"),
                    "configured": config.get("configured", False),
                    "config_path": TELEGRAM_CONFIG_PATH,
                    "chat_count": config.get("chat_count", 0) if config.get("configured") else 0,
                },
            }, indent=2, ensure_ascii=False)

        elif command == "start":
            foreground = kwargs.get("foreground", True)
            if isinstance(foreground, str):
                foreground = foreground.lower() not in ("false", "0", "no", "off", "daemon", "bg")
            result = _start_gateway(foreground=foreground)
            return json.dumps({
                "status": "ok" if result.get("result") not in ("error",) else "error",
                "data": result,
            }, indent=2, ensure_ascii=False)

        elif command == "stop":
            result = _stop_gateway(force=False)
            is_err = result.get("result") in ("error",)
            payload = {"status": "ok", "data": result} if not is_err else {
                "status": "error",
                "error": result.get("message", "Failed to stop gateway"),
                "data": result,
            }
            return json.dumps(payload, indent=2, ensure_ascii=False)

        elif command == "kill":
            result = _stop_gateway(force=True)
            is_err = result.get("result") in ("error",)
            payload = {"status": "ok", "data": result} if not is_err else {
                "status": "error",
                "error": result.get("message", "Failed to kill gateway"),
                "data": result,
            }
            return json.dumps(payload, indent=2, ensure_ascii=False)

        elif command == "restart":
            stop_result = _stop_gateway(force=True)
            fg = kwargs.get("foreground", True)
            if isinstance(fg, str):
                fg = fg.lower() not in ("false", "0", "no", "off", "daemon", "bg")
            start_result = _start_gateway(foreground=fg)
            return json.dumps({
                "status": "ok",
                "data": {
                    "stop": stop_result,
                    "start": start_result,
                },
            }, indent=2, ensure_ascii=False)

        elif command == "health":
            data = _gateway_health_check()
            all_ok = data["configured"] and data["module_available"]
            if all_ok:
                return json.dumps({
                    "status": "ok",
                    "data": data,
                }, indent=2, ensure_ascii=False)
            else:
                issues = []
                if not data["configured"]:
                    issues.append("Telegram not configured")
                if not data["module_available"]:
                    issues.append("Gateway module not importable")
                return json.dumps({
                    "status": "error",
                    "error": f"Health check failed: {'; '.join(issues)}",
                    "data": data,
                }, indent=2, ensure_ascii=False)

        elif command == "help":
            return json.dumps({
                "status": "ok",
                "data": {
                    "commands": sorted(_VALID_COMMANDS),
                    "usage": {
                        "start": "Start the gateway (foreground by default, --daemon for background)",
                        "status": "Check if gateway is running and configured",
                        "stop": "Gracefully stop the gateway (SIGTERM)",
                        "kill": "Force-kill the gateway (SIGKILL)",
                        "restart": "Stop and restart the gateway",
                        "health": "Full health check (running, config, module)",
                        "help": "Show this help",
                    },
                    "config": f"Create {TELEGRAM_CONFIG_PATH} with: "
                              '{"token": "YOUR_BOT_TOKEN", "chat_id": "YOUR_CHAT_ID"}',
                },
            }, indent=2, ensure_ascii=False)

    except Exception:
        return json.dumps({
            "status": "error",
            "error": f"Command '{command}' failed: {traceback.format_exc()[:1000]}",
        }, indent=2, ensure_ascii=False)

    return json.dumps({
        "status": "error",
        "error": f"Command '{command}' not handled.",
    }, indent=2, ensure_ascii=False)


def _print_json(status: str, data: dict | None = None, error: str | None = None) -> None:
    """Print a standardized JSON response."""
    if status == "error":
        print(json.dumps({"status": "error", "error": error or "Unknown error"}, ensure_ascii=False))
    else:
        print(json.dumps({"status": "ok", "data": data or {}}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

        command = sys.argv[1] if len(sys.argv) > 1 else "status"

        kwargs: dict = {}
        for arg in sys.argv[2:]:
            if arg == "--daemon" or arg == "-d":
                kwargs["foreground"] = False
            elif arg == "--foreground" or arg == "-f":
                kwargs["foreground"] = True
            elif arg.startswith("--"):
                if "=" in arg:
                    key, _, val = arg[2:].partition("=")
                    kwargs[key.replace("-", "_")] = val
                else:
                    kwargs[arg[2:].replace("-", "_")] = "true"

        output = gateway_command(command, **kwargs)
        print(output)

    except KeyboardInterrupt:
        _print_json("error", error="Interrupted by user (Ctrl+C)")
        sys.exit(130)
    except Exception:
        _print_json("error", error=f"Unhandled CLI error: {traceback.format_exc()[:1000]}")
        sys.exit(1)
