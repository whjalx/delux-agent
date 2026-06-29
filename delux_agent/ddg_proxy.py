from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

_PROXY_HOST = "127.0.0.1"
_PROXY_PORT = 8765
_PROXY_PROC: subprocess.Popen | None = None


def _needs_proxy(config) -> bool:
    return bool(getattr(config, "plan_free", False))


def _is_running() -> bool:
    try:
        req = urllib.request.Request(f"http://{_PROXY_HOST}:{_PROXY_PORT}/health")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def _cleanup() -> None:
    global _PROXY_PROC
    if _PROXY_PROC and _PROXY_PROC.poll() is None:
        _PROXY_PROC.terminate()
        try:
            _PROXY_PROC.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _PROXY_PROC.kill()
        _PROXY_PROC = None


def _install_playwright_if_missing() -> None:
    try:
        import playwright  # noqa: F401
        return
    except ImportError:
        pass
    print("  [DDG-Proxy] Playwright no instalado. Instalando...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "playwright>=1.40"],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        print(f"  [DDG-Proxy] ERROR instalando Playwright: {exc}", file=sys.stderr)
        return
    print("  [DDG-Proxy] Instalando Chromium...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        print(f"  [DDG-Proxy] ERROR instalando Chromium: {exc}", file=sys.stderr)


def ensure_proxy(config) -> bool:
    """Start DDG-AI Proxy in background if config references it and it's not running.
    Returns True if proxy is (or was already) available."""
    global _PROXY_PROC

    if not _needs_proxy(config):
        return True

    if _is_running():
        return True

    proxy_path = Path(__file__).parent / "ddg_proxy_server.py"
    if not proxy_path.exists():
        print("  [DDG-Proxy] ERROR: ddg_proxy_server.py not found", file=sys.stderr)
        return False

    _install_playwright_if_missing()

    cmd = [sys.executable, str(proxy_path), "--host", _PROXY_HOST, "--port", str(_PROXY_PORT)]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        _PROXY_PROC = subprocess.Popen(
            cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
    except Exception as exc:
        print(f"  [DDG-Proxy] ERROR: {exc}", file=sys.stderr)
        return False

    atexit.register(_cleanup)

    # Wait for it to be ready
    import time
    deadline = time.time() + 20
    started = False
    while time.time() < deadline:
        if _PROXY_PROC.poll() is not None:
            stderr = _PROXY_PROC.stderr.read().decode(errors="replace") if _PROXY_PROC.stderr else ""
            print(f"  [DDG-Proxy] ERROR: process exited early:\n{stderr}", file=sys.stderr)
            return False
        if _is_running():
            started = True
            break
        time.sleep(0.5)

    if not started:
        print("  [DDG-Proxy] ERROR: timed out waiting for server", file=sys.stderr)
        _cleanup()
        return False

    print("  [DDG-Proxy] Auto-started on http://localhost:8765", file=sys.stderr)
    return True


def stop_proxy() -> None:
    """Manually stop the proxy if running."""
    _cleanup()
    atexit.unregister(_cleanup)


def run_ddg_proxy(host: str = "127.0.0.1", port: int = 8765) -> int:
    proxy_path = Path(__file__).parent / "ddg_proxy_server.py"

    cmd = [sys.executable, str(proxy_path), "--host", host, "--port", str(port)]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        proc = subprocess.run(cmd, env=env)
        return proc.returncode
    except KeyboardInterrupt:
        return 0
    except FileNotFoundError:
        print(f"ERROR: Python interpreter not found: {sys.executable}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: Failed to start DDG-AI Proxy: {exc}", file=sys.stderr)
        return 1
