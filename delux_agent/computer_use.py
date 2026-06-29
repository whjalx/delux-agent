from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ComputerResult:
    ok: bool
    output: str


def _require(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "Timed out"
    except FileNotFoundError:
        return -2, f"Command not found: {cmd[0]}"
    except Exception as e:
        return -3, str(e)


def screenshot(output_dir: str | None = None) -> ComputerResult:
    dst_dir = output_dir or "/tmp/delux-computer"
    Path(dst_dir).mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    path = os.path.join(dst_dir, f"screen_{ts}.png")

    if _require("gnome-screenshot"):
        rc, out = _run(["gnome-screenshot", "-f", path], timeout=10)
        if rc == 0 and os.path.exists(path):
            return ComputerResult(True, f"Screenshot saved to {path}")
    if _require("import"):
        rc, out = _run(["import", "-window", "root", path], timeout=10)
        if rc == 0 and os.path.exists(path):
            return ComputerResult(True, f"Screenshot saved to {path}")
    if _require("scrot"):
        rc, out = _run(["scrot", path], timeout=10)
        if rc == 0 and os.path.exists(path):
            return ComputerResult(True, f"Screenshot saved to {path}")

    try:
        import subprocess as sp
        proc = sp.Popen(
            ["python3", "-c", """
import subprocess, sys
try:
    from PIL import Image
    import io
    img = ImageGrab.grab() if hasattr(Image, 'ImageGrab') else None
except:
    pass
print("no PIL")
"""],
            stdout=sp.PIPE, stderr=sp.PIPE,
        )
        proc.wait(timeout=5)
    except Exception:
        pass

    return ComputerResult(False, "No screenshot tool found (install gnome-screenshot, scrot, or import from ImageMagick)")


def click(x: int, y: int, button: str = "left") -> ComputerResult:
    btn_map = {"left": 1, "middle": 2, "right": 3}
    btn = btn_map.get(button, 1)
    if _require("xdotool"):
        rc, out = _run(["xdotool", "mousemove", str(x), str(y), "click", str(btn)], timeout=5)
        return ComputerResult(rc == 0, f"Clicked ({x}, {y}) with {button} button" if rc == 0 else f"Click failed: {out}")
    return ComputerResult(False, "xdotool not available for click")


def type_text(text: str) -> ComputerResult:
    if _require("xdotool"):
        rc, out = _run(["xdotool", "type", "--delay", "50", text], timeout=10)
        return ComputerResult(rc == 0, f"Typed: {text[:100]}" if rc == 0 else f"Type failed: {out}")
    return ComputerResult(False, "xdotool not available for typing")


def keypress(key: str) -> ComputerResult:
    if _require("xdotool"):
        rc, out = _run(["xdotool", "key", key], timeout=5)
        return ComputerResult(rc == 0, f"Pressed: {key}" if rc == 0 else f"Keypress failed: {out}")
    return ComputerResult(False, "xdotool not available for keypress")


def drag(x1: int, y1: int, x2: int, y2: int) -> ComputerResult:
    if _require("xdotool"):
        rc1, _ = _run(["xdotool", "mousemove", str(x1), str(y1)], timeout=3)
        rc2, out = _run(["xdotool", "mousedown", "1", "mousemove", str(x2), str(y2), "mouseup", "1"], timeout=5)
        return ComputerResult(rc2 == 0, f"Dragged from ({x1},{y1}) to ({x2},{y2})" if rc2 == 0 else f"Drag failed: {out}")
    return ComputerResult(False, "xdotool not available for drag")


def get_screen_size() -> ComputerResult:
    if _require("xdotool"):
        rc, out = _run(["xdotool", "getdisplaygeometry"], timeout=3)
        if rc == 0:
            return ComputerResult(True, f"Screen size: {out}")
    return ComputerResult(False, "Could not determine screen size")
