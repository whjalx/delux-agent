#!/usr/bin/env python3
"""Web search via ddgr — production-grade JSON output."""
import json
import shutil
import subprocess
import sys

_DDGR_BIN = "ddgr"
_MAX_QUERY_LENGTH = 500
_SEARCH_LIMIT = 5
_TIMEOUT = 20


def _validate_query(query):
    """Return (validated_query, error_message)."""
    if query is None:
        return None, "query is None"
    if not isinstance(query, str):
        return None, f"query must be a string, got {type(query).__name__}"
    stripped = query.strip()
    if not stripped:
        return None, "query is empty"
    if len(stripped) > _MAX_QUERY_LENGTH:
        return None, f"query too long ({len(stripped)} > {_MAX_QUERY_LENGTH} chars)"
    # Reject potentially dangerous shell metacharacters (ddgr handles quoting but be safe)
    if "\x00" in stripped:
        return None, "query contains null byte"
    return stripped, None


def search(query):
    """Execute ddgr search and return JSON result dict."""
    validated, err = _validate_query(query)
    if err:
        return {"status": "error", "error": err}

    # Check ddgr installed
    if not shutil.which(_DDGR_BIN):
        return {"status": "error", "error": f"{_DDGR_BIN} is not installed or not in PATH"}

    cmd = [_DDGR_BIN, "--json", "-n", str(_SEARCH_LIMIT), validated]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return {"status": "error", "error": f"{_DDGR_BIN} not found"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "search timed out"}
    except PermissionError:
        return {"status": "error", "error": f"permission denied executing {_DDGR_BIN}"}
    except OSError as exc:
        return {"status": "error", "error": f"OS error running {_DDGR_BIN}: {exc}"}

    stderr_text = (proc.stderr or "").strip().lower()
    stdout_text = (proc.stdout or "").strip()

    # Detect rate limiting or DDG blocking
    if proc.returncode != 0 and ("rate limit" in stderr_text or "403" in stderr_text or "blocked" in stderr_text):
        return {"status": "error", "error": "rate limited or blocked by DuckDuckGo", "detail": proc.stderr[:300]}
    if "duckduckgo" in stderr_text and ("unavailable" in stderr_text or "error" in stderr_text or "failed" in stderr_text):
        return {"status": "error", "error": "DuckDuckGo unavailable", "detail": proc.stderr[:300]}

    if proc.returncode != 0:
        return {"status": "error",
                "error": f"{_DDGR_BIN} exited with code {proc.returncode}",
                "stderr": (proc.stderr or "")[:300]}

    if not stdout_text:
        return {"status": "ok", "data": {"query": validated, "results": [], "count": 0}}

    # Parse JSON output
    try:
        raw_data = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        return {"status": "error",
                "error": f"failed to parse ddgr JSON output: {exc}",
                "raw_stdout": stdout_text[:500]}

    if not isinstance(raw_data, list):
        return {"status": "error", "error": f"unexpected ddgr output type: {type(raw_data).__name__}"}

    results = []
    for item in raw_data:
        if not isinstance(item, dict):
            continue
        results.append({
            "title": str(item.get("title", "No Title")),
            "url": str(item.get("url", "")),
            "abstract": str(item.get("abstract", "")),
        })

    return {"status": "ok", "data": {"query": validated, "results": results, "count": len(results)}}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"status": "error",
                          "error": "usage: delux-quick-search <query>",
                          "help": "Provide a search query as argument(s)"}))
        sys.exit(1)

    query = " ".join(sys.argv[1:]).strip()
    result = search(query)
    print(json.dumps(result))
    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
