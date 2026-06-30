from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SubagentResult:
    ok: bool
    output: str
    steps: list[dict] = field(default_factory=list)


def spawn_subagent(
    task: str,
    config_root: str | None = None,
    cwd: str | None = None,
    max_steps: int = 90,
    timeout: int = 120,
    toolsets: list[str] | None = None,
) -> SubagentResult:
    root = Path(config_root or os.environ.get("DELUX_HOME", Path.home() / ".delux"))
    workdir = Path(cwd or os.getcwd())
    delux_bin = None

    venv = Path(sys.prefix)
    candidates = [
        venv / "bin" / "delux",
        venv.parent / "bin" / "delux",
        Path(sys.executable).parent / "delux",
        Path.home() / "project" / "delux-agent" / ".venv" / "bin" / "delux",
    ]
    for c in candidates:
        if c.exists():
            delux_bin = str(c)
            break

    if delux_bin is None:
        delux_bin = shutil_which("delux")
    if delux_bin is None:
        return SubagentResult(False, "delux binary not found for subagent")

    env = os.environ.copy()
    env["DELUX_HOME"] = str(root)
    env["DELUX_AGENT_SUB"] = "1"

    try:
        proc = subprocess.run(
            [delux_bin, "--cwd", str(workdir), "--home", str(root), "--max-steps", str(max_steps), task],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (proc.stdout + proc.stderr).strip()
        return SubagentResult(proc.returncode == 0, output)
    except subprocess.TimeoutExpired:
        return SubagentResult(False, f"Subagent timed out after {timeout}s")
    except FileNotFoundError:
        return SubagentResult(False, f"delux binary not found at {delux_bin}")
    except Exception as e:
        return SubagentResult(False, f"Subagent execution failed: {e}")


def shutil_which(cmd: str) -> str | None:
    try:
        import shutil
        return shutil.which(cmd)
    except Exception:
        return None
