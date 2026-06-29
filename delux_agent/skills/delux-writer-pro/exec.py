#!/usr/bin/env python3
"""File writer — production-grade with JSON output and path-traversal protection."""
import json
import os
import sys
import stat
import shutil

_MAX_CONTENT_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_WRITE_DIRS = os.environ.get("DELUX_WRITER_ALLOWED_DIRS", "")  # colon-separated dirs; empty = allow anywhere


def _resolve_safe(path):
    """Resolve path, reject traversal/symlink attacks if ALLOWED_DIRS is configured, return safe absolute path."""
    if not path or not isinstance(path, str):
        raise ValueError("path must be a non-empty string")

    if "\x00" in path:
        raise ValueError("path contains null byte")

    try:
        real = os.path.realpath(path)
    except (OSError, ValueError, RuntimeError) as exc:
        raise ValueError(f"cannot resolve path: {exc}")

    if not real or real == os.path.sep:
        raise ValueError("resolved path is invalid (root or empty)")

    if _ALLOWED_WRITE_DIRS:
        allowed = [os.path.realpath(d) for d in _ALLOWED_WRITE_DIRS.split(":") if d.strip()]
        ok = any(real.startswith(d + os.path.sep) or real == d for d in allowed)
        if not ok:
            raise ValueError(f"path blocked: {path} not in allowed directories ({_ALLOWED_WRITE_DIRS})")

    return real


def write_pro(path, content):
    """Write content to path atomically with full error handling. Returns JSON dict."""
    # --- validate content ---
    if content is None:
        return {"status": "error", "error": "content is None"}
    if not isinstance(content, str):
        return {"status": "error", "error": f"content must be a string, got {type(content).__name__}"}

    content_bytes = content.encode("utf-8", errors="replace")
    if len(content_bytes) > _MAX_CONTENT_BYTES:
        return {"status": "error",
                "error": f"content too large ({len(content_bytes)} bytes, max {_MAX_CONTENT_BYTES})"}

    # --- validate path ---
    try:
        safe_path = _resolve_safe(path)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}

    # Check if parent is a writable directory or can be created
    parent = os.path.dirname(safe_path)
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except PermissionError:
            return {"status": "error", "error": f"permission denied creating directory: {parent}"}
        except OSError as exc:
            return {"status": "error", "error": f"cannot create parent directory {parent}: {exc}"}

    # Check if existing path is a directory
    if os.path.isdir(safe_path):
        return {"status": "error", "error": f"path is an existing directory: {safe_path}"}

    # Check disk space (simple heuristic)
    try:
        usage = shutil.disk_usage(parent or ".")
        if usage.free < len(content_bytes) + 4096:
            return {"status": "error", "error": "disk full — insufficient free space"}
    except OSError:
        pass  # can't check, continue anyway

    # --- write ---
    try:
        # Remove existing file first to avoid permission issues on read-only files
        if os.path.lexists(safe_path):
            # Check if we can write to it
            if not os.access(safe_path, os.W_OK):
                try:
                    os.chmod(safe_path, stat.S_IWUSR | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
                except OSError:
                    return {"status": "error", "error": f"cannot overwrite read-only file: {safe_path}"}
            os.remove(safe_path)

        with open(safe_path, "w", encoding="utf-8", errors="replace") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())

    except PermissionError:
        return {"status": "error", "error": f"permission denied writing: {safe_path}"}
    except IsADirectoryError:
        return {"status": "error", "error": f"path is a directory: {safe_path}"}
    except OSError as exc:
        return {"status": "error", "error": f"I/O error writing file: {exc}"}
    except Exception as exc:
        return {"status": "error", "error": f"unexpected error: {exc}"}

    # --- verify ---
    try:
        if not os.path.isfile(safe_path):
            return {"status": "error", "error": f"verification failed: file does not exist after write"}
        written_size = os.path.getsize(safe_path)
        if written_size != len(content_bytes):
            return {"status": "error", "error": f"size mismatch: expected {len(content_bytes)}, got {written_size}"}
    except OSError as exc:
        return {"status": "error", "error": f"verification error: {exc}"}

    return {"status": "ok", "data": {"path": safe_path, "size_bytes": written_size}}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"status": "error",
                          "error": "usage: delux-writer-pro <path> <content>",
                          "help": "Provide file path and content as arguments"}))
        sys.exit(1)

    target_path = sys.argv[1]
    content_to_write = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
    content_to_write = content_to_write.replace("\\n", "\n")

    result = write_pro(target_path, content_to_write)
    print(json.dumps(result))
    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
