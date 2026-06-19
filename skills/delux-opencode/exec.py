import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap


OPENCODE_TIMEOUT = 300


def _find_opencode() -> str | None:
    return shutil.which("opencode")


def run_opencode(prompt: str, cwd: str | None = None, timeout: int = OPENCODE_TIMEOUT) -> dict:
    binary = _find_opencode()
    if not binary:
        return {
            "status": "error",
            "error": "opencode not found in PATH. Install with: pip install opencode"
        }

    workdir = cwd or os.getcwd()

    try:
        proc = subprocess.run(
            [binary, "run", prompt],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        result = {
            "status": "ok" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "output": stdout[:10000] if stdout else "",
            "errors": stderr[:2000] if stderr else "",
        }

        if not stdout and not stderr:
            result["output"] = f"OpenCode completed with exit code {proc.returncode}"

        return result

    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": f"OpenCode timed out after {timeout}s. Try a more specific prompt."
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "error": "opencode binary not found despite which() succeeding"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)[:500]
        }


def opencode_task(prompt: str, cwd: str | None = None) -> str:
    result = run_opencode(prompt, cwd)
    return json.dumps(result, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: delux-opencode <prompt>"}))
        sys.exit(1)

    prompt = " ".join(sys.argv[1:])
    cwd = os.environ.get("DELUX_CWD", None)
    print(opencode_task(prompt, cwd))
