from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path


def get_system_info() -> str:
    lines: list[str] = []
    try:
        lines.append(f"os:{platform.system()} {platform.release()}")
    except Exception:
        lines.append(f"os:{platform.system()}")
    try:
        lines.append(f"arch:{platform.machine()}")
    except Exception:
        pass
    try:
        lines.append(f"host:{platform.node()}")
    except Exception:
        pass
    try:
        lines.append(f"cpu:{os.cpu_count()} cores")
    except Exception:
        pass
    try:
        if platform.system() == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        lines.append(f"ram:{kb // 1024}MB")
                        break
        elif platform.system() == "Darwin":
            proc = os.popen("sysctl hw.memsize 2>/dev/null")
            out = proc.read()
            proc.close()
            if out:
                lines.append(f"ram:{int(out.split(':')[1].strip()) // (1024**3)}GB")
    except Exception:
        pass
    try:
        usage = shutil.disk_usage("/")
        lines.append(f"disk:{usage.total // (2**30)}GB total, {usage.free // (2**30)}GB free")
    except Exception:
        pass
    try:
        shell = os.environ.get("SHELL", "sh")
        lines.append(f"shell:{shell}")
    except Exception:
        pass
    try:
        home = Path.home()
        delux_home = Path(os.environ.get("DELUX_HOME", home / ".delux"))
        if delux_home.exists():
            skills_count = len(list(delux_home.glob("skills/*/SKILL.md")))
            lines.append(f"delux_home:{delux_home} ({skills_count} skills)")
    except Exception:
        pass
    try:
        cwd = Path.cwd()
        lines.append(f"cwd:{cwd}")
    except Exception:
        pass
    return "\n".join(lines)


def get_project_tree(path: str | Path = ".", max_depth: int = 2, max_items: int = 25) -> str:
    path = Path(path)
    if not path.is_dir():
        return f"tree:{path} (not a directory)"
    lines: list[str] = []
    count = 0

    def _walk(p: Path, depth: int):
        nonlocal count
        if count >= max_items:
            return
        try:
            entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name))
        except PermissionError:
            return
        hide = {".git", "__pycache__", "node_modules", ".venv", ".cache", ".tox", "egg-info", ".pytest_cache"}
        for e in entries:
            if count >= max_items:
                return
            if e.name.startswith(".") and e.name not in (".env", ".config"):
                continue
            if e.name in hide:
                continue
            indent = "  " * depth
            if e.is_dir():
                if depth < max_depth:
                    lines.append(f"{indent}{e.name}/")
                    _walk(e, depth + 1)
                else:
                    lines.append(f"{indent}{e.name}/...")
                count += 1
            else:
                try:
                    size = e.stat().st_size
                    size_str = f"{size}B" if size < 1024 else f"{size // 1024}KB" if size < 1024 * 1024 else f"{size // (1024*1024)}MB"
                    lines.append(f"{indent}{e.name} ({size_str})")
                except OSError:
                    lines.append(f"{indent}{e.name}")
                count += 1

    lines.append(f"tree:{path.name}/")
    _walk(path, 1)
    if count >= max_items:
        lines.append("  ... (truncated)")
    return "\n".join(lines)


def get_compact_context(path: str | Path = ".") -> str:
    info = get_system_info()
    tree = get_project_tree(path, max_depth=2, max_items=20)
    return f"[system]\n{info}\n\n[project]\n{tree}"
