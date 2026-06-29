#!/usr/bin/env python3
"""OpenCode subprocess runner — production-grade CLI with JSON output."""

import json
import os
import shutil
import subprocess
import sys
import time
import traceback

DEFAULT_TIMEOUT = 300
MAX_TIMEOUT = 3600
MIN_TIMEOUT = 10
MAX_OUTPUT_CHARS = 50000
MAX_STDERR_CHARS = 10000
MAX_PROMPT_CHARS = 100000


def _find_opencode() -> str | None:
    """Locate the opencode binary. Returns path or None."""
    return shutil.which("opencode")


def _validate_prompt(prompt: str) -> str:
    """Validate and sanitize the prompt string."""
    if not prompt or not isinstance(prompt, str):
        raise ValueError("Prompt is required and must be a non-empty string")
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("Prompt is required and must be a non-empty string")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"Prompt too long ({len(prompt)} chars, max {MAX_PROMPT_CHARS})")
    prompt_clean = prompt.replace("\x00", "")
    return prompt_clean


def _validate_cwd(cwd: str | None) -> str | None:
    """Validate the working directory path."""
    if cwd is None:
        return None
    if not isinstance(cwd, str):
        raise ValueError("Working directory must be a string path")
    cwd = cwd.strip()
    if not cwd:
        return None
    cwd = os.path.expanduser(cwd)
    if not os.path.exists(cwd):
        raise ValueError(f"Working directory does not exist: {cwd}")
    if not os.path.isdir(cwd):
        raise ValueError(f"Path is not a directory: {cwd}")
    if not os.access(cwd, os.R_OK | os.X_OK):
        raise ValueError(f"Permission denied for working directory: {cwd}")
    return os.path.abspath(cwd)


def _validate_timeout(val: int | str | None) -> int:
    """Validate and clamp timeout value."""
    if val is None:
        return DEFAULT_TIMEOUT
    try:
        val = int(val)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid timeout value: '{val}'. Must be an integer (seconds)")
    if val < MIN_TIMEOUT:
        raise ValueError(f"Timeout must be at least {MIN_TIMEOUT} seconds, got {val}")
    if val > MAX_TIMEOUT:
        raise ValueError(f"Timeout must be at most {MAX_TIMEOUT} seconds, got {val}")
    return val


def _truncate_output(text: str, max_chars: int, label: str = "output") -> dict:
    """Truncate text smartly, returning dict with text and metadata."""
    if not text:
        return {"text": "", "truncated": False, "original_size": 0}
    original_size = len(text)
    if original_size <= max_chars:
        return {"text": text, "truncated": False, "original_size": original_size}

    head = max_chars // 2
    tail = max_chars // 2
    truncated = (
        text[:head]
        + f"\n\n... [{original_size - head - tail} characters truncated] ...\n\n"
        + text[-tail:]
    )
    return {
        "text": truncated,
        "truncated": True,
        "original_size": original_size,
        "truncated_size": len(truncated),
    }


def run_opencode(
    prompt: str,
    cwd: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Run an OpenCode prompt. Returns result dict."""
    binary = _find_opencode()
    if not binary:
        return {
            "status": "error",
            "error": (
                "OpenCode is not installed or not found in PATH. "
                "Install with: pip install opencode"
            ),
        }

    try:
        prompt = _validate_prompt(prompt)
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    try:
        workdir = _validate_cwd(cwd) or os.getcwd()
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    try:
        timeout = _validate_timeout(timeout)
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    start_time = time.monotonic()

    try:
        proc = subprocess.run(
            [binary, "run", prompt],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start_time
        return {
            "status": "error",
            "error": f"OpenCode timed out after {timeout}s (waited {elapsed:.1f}s). Try a more specific prompt.",
            "returncode": -1,
            "execution_time": round(elapsed, 3),
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "error": (
                f"OpenCode binary not found at '{binary}'. This is unexpected — "
                "the binary was located by which() but could not be executed. "
                "Check for broken symlinks or PATH inconsistencies."
            ),
        }
    except PermissionError:
        return {
            "status": "error",
            "error": f"Permission denied executing OpenCode at '{binary}'. Check file permissions.",
        }
    except subprocess.SubprocessError as e:
        elapsed = time.monotonic() - start_time
        return {
            "status": "error",
            "error": f"Subprocess error running OpenCode: {str(e)[:500]}",
            "execution_time": round(elapsed, 3),
        }

    elapsed = time.monotonic() - start_time

    stdout_raw = proc.stdout or ""
    stderr_raw = proc.stderr or ""

    stdout_info = _truncate_output(stdout_raw.strip(), MAX_OUTPUT_CHARS, "stdout")
    stderr_info = _truncate_output(stderr_raw.strip(), MAX_STDERR_CHARS, "stderr")

    if not stdout_raw.strip() and not stderr_raw.strip():
        stdout_info = {
            "text": f"OpenCode completed with exit code {proc.returncode} (no output)",
            "truncated": False,
            "original_size": 0,
        }

    success = proc.returncode == 0

    return {
        "status": "ok" if success else "error",
        "data": {
            "returncode": proc.returncode,
            "output": stdout_info["text"],
            "output_truncated": stdout_info.get("truncated", False),
            "output_original_size": stdout_info.get("original_size", 0),
            "stderr": stderr_info["text"],
            "stderr_truncated": stderr_info.get("truncated", False),
            "stderr_original_size": stderr_info.get("original_size", 0),
            "execution_time": round(elapsed, 3),
            "cwd": workdir,
            "command": [binary, "run", prompt[:200] + ("..." if len(prompt) > 200 else "")],
        },
    }


def opencode_task(prompt: str, cwd: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Main entry point. Returns JSON string."""
    try:
        result = run_opencode(prompt, cwd=cwd, timeout=timeout)
    except Exception:
        result = {
            "status": "error",
            "error": f"Unhandled error: {traceback.format_exc()[:1000]}",
        }
    return json.dumps(result, indent=2, ensure_ascii=False, default=str)


def _print_json(status: str, data: dict | None = None, error: str | None = None) -> None:
    """Print a standardized JSON response."""
    if status == "error":
        print(json.dumps({"status": "error", "error": error or "Unknown error"}, ensure_ascii=False))
    else:
        print(json.dumps({"status": "ok", "data": data or {}}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        args = sys.argv[1:]
        cwd = os.environ.get("DELUX_CWD", None)
        timeout = DEFAULT_TIMEOUT

        i = 0
        positional: list[str] = []
        while i < len(args):
            if args[i] == "--timeout" and i + 1 < len(args):
                timeout = args[i + 1]
                i += 2
            elif args[i].startswith("--timeout="):
                timeout = args[i].split("=", 1)[1]
                i += 1
            elif args[i] == "--cwd" and i + 1 < len(args):
                cwd = args[i + 1]
                i += 2
            elif args[i].startswith("--cwd="):
                cwd = args[i].split("=", 1)[1]
                i += 1
            else:
                positional.append(args[i])
                i += 1

        prompt = " ".join(positional)

        if not prompt:
            _print_json("error", error="No prompt provided. Usage: delux-opencode [--timeout SECS] [--cwd PATH] <prompt>")
            sys.exit(1)

        try:
            timeout_int = _validate_timeout(timeout)
        except ValueError as e:
            _print_json("error", error=str(e))
            sys.exit(1)

        output = opencode_task(prompt, cwd=cwd, timeout=timeout_int)
        print(output)

    except KeyboardInterrupt:
        _print_json("error", error="Interrupted by user (Ctrl+C)")
        sys.exit(130)
    except Exception:
        _print_json("error", error=f"Unhandled CLI error: {traceback.format_exc()[:1000]}")
        sys.exit(1)
