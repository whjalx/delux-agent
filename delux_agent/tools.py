from __future__ import annotations

import difflib
import os
import re
import selectors
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .store import EXEC_EXT_MAP, append_note, load_skills, slugify, upsert_skill


COMMAND_NOT_FOUND_PATTERNS = [
    "command not found",
    "not found",
    "no se ha encontrado",
    "no se encontró",
    "comando no encontrado",
    "executable not found",
    "no such file or directory",
    "cannot execute",
    "command not found in PATH",
    "fish: Unknown command",
]

PACKAGE_DETECTORS = {
    "dnf": {"check": ["dnf", "--version"], "install": "sudo dnf install -y {pkg}", "desc": "dnf (Fedora/RHEL)"},
    "apt": {"check": ["apt-get", "--version"], "install": "sudo apt-get install -y {pkg}", "desc": "apt (Debian/Ubuntu)"},
    "pacman": {"check": ["pacman", "--version"], "install": "sudo pacman -S --noconfirm {pkg}", "desc": "pacman (Arch)"},
    "zypper": {"check": ["zypper", "--version"], "install": "sudo zypper install -y {pkg}", "desc": "zypper (openSUSE)"},
    "brew": {"check": ["brew", "--version"], "install": "brew install {pkg}", "desc": "Homebrew (macOS/Linux)"},
    "nix-env": {"check": ["nix-env", "--version"], "install": "nix-env -iA nixpkgs.{pkg}", "desc": "Nix"},
    "pip": {"check": ["pip3", "--version"], "install": "pip3 install {pkg}", "desc": "pip (Python)"},
    "npm": {"check": ["npm", "--version"], "install": "npm install -g {pkg}", "desc": "npm (Node.js)"},
    "cargo": {"check": ["cargo", "--version"], "install": "cargo install {pkg}", "desc": "Cargo (Rust)"},
    "go": {"check": ["go", "version"], "install": "go install {pkg}@latest", "desc": "Go"},
    "gem": {"check": ["gem", "--version"], "install": "gem install {pkg}", "desc": "RubyGems"},
}

KNOWN_PACKAGES = {
    "rg": {"pkg": "ripgrep", "managers": ["dnf", "apt", "pacman", "brew"]},
    "fd": {"pkg": "fd-find", "managers": ["dnf", "apt", "pacman", "brew"]},
    "jq": {"pkg": "jq", "managers": ["dnf", "apt", "pacman", "brew"]},
    "fzf": {"pkg": "fzf", "managers": ["dnf", "apt", "pacman", "brew"]},
    "bat": {"pkg": "bat", "managers": ["dnf", "apt", "pacman", "brew"]},
    "htop": {"pkg": "htop", "managers": ["dnf", "apt", "pacman", "brew"]},
    "tree": {"pkg": "tree", "managers": ["dnf", "apt", "pacman", "brew"]},
    "wget": {"pkg": "wget", "managers": ["dnf", "apt", "pacman", "brew"]},
    "curl": {"pkg": "curl", "managers": ["dnf", "apt", "pacman", "brew"]},
    "git": {"pkg": "git", "managers": ["dnf", "apt", "pacman", "brew"]},
    "python3": {"pkg": "python3", "managers": ["dnf", "apt", "pacman", "brew"]},
    "node": {"pkg": "nodejs", "managers": ["dnf", "apt", "pacman", "brew"]},
    "npm": {"pkg": "npm", "managers": ["dnf", "apt", "pacman", "brew"]},
    "go": {"pkg": "golang", "managers": ["dnf", "apt", "pacman", "brew"]},
    "rustc": {"pkg": "rust", "managers": ["dnf", "apt", "pacman", "brew"]},
    "docker": {"pkg": "docker", "managers": ["dnf", "apt", "pacman", "brew"]},
    "make": {"pkg": "make", "managers": ["dnf", "apt", "pacman", "brew"]},
    "cmake": {"pkg": "cmake", "managers": ["dnf", "apt", "pacman", "brew"]},
    "gcc": {"pkg": "gcc", "managers": ["dnf", "apt", "pacman", "brew"]},
    "tmux": {"pkg": "tmux", "managers": ["dnf", "apt", "pacman", "brew"]},
    "neovim": {"pkg": "neovim", "managers": ["dnf", "apt", "pacman", "brew"]},
    "vim": {"pkg": "vim", "managers": ["dnf", "apt", "pacman", "brew"]},
    "zsh": {"pkg": "zsh", "managers": ["dnf", "apt", "pacman", "brew"]},
    "fish": {"pkg": "fish", "managers": ["dnf", "apt", "pacman", "brew"]},
    "lazygit": {"pkg": "lazygit", "managers": ["dnf", "apt", "pacman", "brew", "go"]},
    "bat": {"pkg": "bat", "managers": ["dnf", "apt", "pacman", "brew"]},
    "eza": {"pkg": "eza", "managers": ["dnf", "apt", "pacman", "brew"]},
    "starship": {"pkg": "starship", "managers": ["dnf", "apt", "pacman", "brew"]},
    "delta": {"pkg": "delta", "managers": ["dnf", "apt", "pacman", "brew"]},
    "bottom": {"pkg": "bottom", "managers": ["dnf", "apt", "pacman", "brew", "cargo"]},
    "duf": {"pkg": "duf", "managers": ["dnf", "apt", "pacman", "brew"]},
    "broot": {"pkg": "broot", "managers": ["dnf", "apt", "pacman", "brew", "cargo"]},
    "zoxide": {"pkg": "zoxide", "managers": ["dnf", "apt", "pacman", "brew", "cargo"]},
    "atuin": {"pkg": "atuin", "managers": ["dnf", "apt", "pacman", "brew", "cargo"]},
    "yazi": {"pkg": "yazi", "managers": ["cargo"]},
    "eza": {"pkg": "eza", "managers": ["dnf", "apt", "pacman", "brew"]},
    "lsd": {"pkg": "lsd", "managers": ["cargo"]},
    "rip": {"pkg": "rip", "managers": ["cargo"]},
}

BLOCKED_COMMANDS = {"sudo", "su", "doas", "pkexec", "passwd", "visudo"}


def resolve_path(path: str, base: Path) -> Path:
    target = Path(path)
    spath = str(path)
    if spath.startswith("~"):
        target = Path(path).expanduser()
    elif spath.startswith(".delux"):
        delux_home = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
        rest = spath[len(".delux"):].lstrip("/")
        target = (delux_home / rest).resolve()
    elif not target.is_absolute():
        target = (base / target).resolve()
    else:
        target = target.resolve()
    return target


def _resolve_for_read(path: str, base: Path) -> Path:
    target = resolve_path(path, base)
    if target.exists():
        return target
    if not path.startswith("/") and not path.startswith("~"):
        clean = path
        if clean.startswith("skills/"):
            clean = clean[len("skills/"):]
        # Try built-in skills dir
        fallback = _builtin_skills_dir() / clean
        if fallback.exists():
            return fallback
        # Try user skills dir (~/.delux/skills/)
        delux_home = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
        fallback = delux_home / "skills" / clean
        if fallback.exists():
            return fallback
    return target


def check_path_safety(target: Path, base: Path, root: Path) -> str | None:
    try:
        target.resolve().relative_to(base.resolve())
        return None
    except ValueError:
        pass
    try:
        target.resolve().relative_to(root.resolve())
        return None
    except ValueError:
        pass
    if target == base or target == root:
        return None
    return (
        f"WARNING: path {target} is outside both the working directory "
        f"({base}) and DELUX_HOME ({root}). "
        f"Use absolute paths to access files outside these locations."
    )


def _builtin_skills_dir() -> Path:
    import delux_agent
    return Path(delux_agent.__file__).parent / "skills"


def _check_builtin_write(path: str, cwd: Path) -> str | None:
    target = resolve_path(path, cwd)
    try:
        target.resolve().relative_to(_builtin_skills_dir().resolve())
        return (
            f"ERROR: Cannot modify `{target.name}` — it is a built-in skill.\n"
            f"Built-in skills are read-only. To customize a built-in skill, "
            f"copy it to DELUX_HOME/skills/ and edit the copy instead."
        )
    except ValueError:
        return None


def _is_binary(filepath: Path, sample_bytes: int = 1024) -> bool:
    try:
        with filepath.open("rb") as f:
            chunk = f.read(sample_bytes)
        if b"\x00" in chunk:
            return True
        text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x7F)) | set(range(0x80, 0x100)))
        if chunk.translate(None, text_chars):
            return True
        return False
    except OSError:
        return False


def _read_with_fallback(filepath: Path, max_size: int = 0) -> str:
    encodings = ["utf-8", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            text = filepath.read_text(encoding=enc)
            if max_size > 0 and len(text) > max_size:
                text = text[:max_size]
                text += f"\n[... truncated at {max_size} chars, {filepath.stat().st_size} total]"
            return text
        except UnicodeDecodeError:
            continue
        except OSError:
            break
    return ""


def _atomic_write(filepath: Path, content: str) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp", prefix="." + filepath.name + ".", dir=filepath.parent
    )
    try:
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        os.replace(tmp_path, filepath)
    except Exception:
        os.close(fd)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _create_backup(filepath: Path) -> Path | None:
    backup = filepath.with_suffix(filepath.suffix + ".bak")
    try:
        shutil.copy2(str(filepath), str(backup))
        return backup
    except OSError:
        return None


def _fmt_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f}MB"


def _detect_package_manager() -> str | None:
    for mgr, info in PACKAGE_DETECTORS.items():
        if mgr in {"pip", "npm", "cargo", "go", "gem"}:
            continue
        if shutil.which(mgr):
            return mgr
    return None


def _suggest_package_install(cmd: str) -> str | None:
    base = cmd.split("/")[-1].strip("\"'")
    known = KNOWN_PACKAGES.get(base)
    if not known:
        return None
    pkg = known["pkg"]
    manager = _detect_package_manager()
    if manager and manager in known["managers"]:
        install_cmd = PACKAGE_DETECTORS[manager]["install"].format(pkg=pkg)
        return f"[Suggestion] `{base}` is not installed. Install with: {install_cmd} ({PACKAGE_DETECTORS[manager]['desc']})"
    options = []
    for mgr in known["managers"]:
        if mgr in PACKAGE_DETECTORS:
            options.append(f"{PACKAGE_DETECTORS[mgr]['install'].format(pkg=pkg)} ({PACKAGE_DETECTORS[mgr]['desc']})")
    if options:
        return f"[Suggestion] `{base}` is not installed. Options:\n" + "\n".join(f"  - {o}" for o in options)
    return None


def _enhance_error(output: str) -> str:
    output_lower = output.lower()
    for pattern in COMMAND_NOT_FOUND_PATTERNS:
        if pattern.lower() in output_lower:
            cmd_candidates: list[str] = []
            import re
            for line in output.strip().split("\n"):
                line_lower = line.lower()
                if "unknown command" in line_lower or "not found" in line_lower or "command not found" in line_lower:
                    quoted = re.findall(r'["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]', line)
                    if quoted:
                        cmd_candidates.extend(quoted)
                    else:
                        bash_match = re.search(r'\w+:\s*(\w+):\s*command not found', line)
                        if bash_match:
                            cmd_candidates.append(bash_match.group(1))
                        else:
                            zsh_match = re.search(r'command not found:\s*(\w+)', line)
                            if zsh_match:
                                cmd_candidates.append(zsh_match.group(1))
                            else:
                                tokens = line.strip().split()
                                last_token = tokens[-1].strip("\"':;,!()[]{}") if tokens else ""
                                if len(last_token) > 1 and last_token.isalnum():
                                    cmd_candidates.append(last_token)
            for cmd_name in cmd_candidates:
                suggestion = _suggest_package_install(cmd_name)
                if suggestion:
                    return output + "\n\n" + suggestion
            break
    return output


RUNTIME_CMD = {
    "bash": ["bash"],
    "fish": ["fish"],
    "python3": ["python3"],
    "go": ["go", "run"],
    "node": ["node"],
    "ruby": ["ruby"],
    "rust": ["cargo", "script"],
}


@dataclass
class ToolResult:
    ok: bool
    output: str


def _inside_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def validate_command(command: str) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return f"Invalid shell syntax: {exc}"
    for token in tokens:
        if token in BLOCKED_COMMANDS or token.split("/")[-1] in BLOCKED_COMMANDS:
            return f"Blocked command `{token}`. Delux never escalates privileges."
    return None


def run_shell(
    command: str,
    cwd: Path,
    shell_name: str,
    timeout: int = 60,
    stream_callback: Callable[[str], None] | None = None,
) -> ToolResult:
    blocked = validate_command(command)
    if blocked:
        return ToolResult(False, blocked)

    # Prefer sh for reliability (no config sourcing, POSIX-compliant, fast).
    # Falls back through the chain if sh is somehow unavailable.
    shell = shutil.which("sh") or shutil.which("bash") or shutil.which(shell_name) or "/bin/sh"
    args = [shell, "-c", command]
    env = os.environ.copy()
    env["DELUX_AGENT"] = "1"
    env["FISH_GREETING"] = ""
    # Suppress interactive shell features
    env["TERM"] = "dumb"
    env["PROMPT_COMMAND"] = ""
    env["PS1"] = ""
    env["PS2"] = ""
    env["XDG_CONFIG_HOME"] = "/dev/null"
    proc: subprocess.Popen[bytes] | None = None
    try:
        proc = subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert proc.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        chunks: list[str] = []

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                proc.wait()
                partial = "".join(chunks).strip()
                if partial:
                    partial += "\n"
                return ToolResult(False, f"{partial}Command timed out after {timeout}s: {command}".strip())

            events = selector.select(timeout=min(0.2, remaining))
            if events:
                for key, _ in events:
                    data = os.read(key.fileobj.fileno(), 4096)
                    if not data:
                        # EOF — process closed stdout
                        selector.unregister(key.fileobj)
                        continue
                    text = data.decode("utf-8", errors="replace")
                    chunks.append(text)
                    if stream_callback:
                        stream_callback(text)
            if proc.poll() is not None:
                break

        proc.wait()
        tail = b""
        if proc.stdout:
            try:
                tail = os.read(proc.stdout.fileno(), 4096)
            except OSError:
                tail = b""
        if tail:
            text = tail.decode("utf-8", errors="replace")
            chunks.append(text)
            if stream_callback:
                stream_callback(text)
        output = "".join(chunks).strip()
        output = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', output)
        output = re.sub(r'\x1b\([0-9A-Za-z]', '', output)
        enhanced = _enhance_error(output) if proc.returncode != 0 else output
        return ToolResult(proc.returncode == 0, enhanced or f"exit code {proc.returncode}")
    except OSError as exc:
        return ToolResult(False, f"Failed to run command: {exc}")
    except KeyboardInterrupt:
        if proc:
            proc.kill()
            proc.wait()
        return ToolResult(False, f"Command interrupted: {command}")
    finally:
        if proc and proc.stdout:
            proc.stdout.close()


def read_file(path: str, base: Path) -> ToolResult:
    target = _resolve_for_read(path, base)
    if not target.exists():
        return ToolResult(False, f"File not found: {path}")
    if not target.is_file():
        return ToolResult(False, f"Not a file (directory or special): {path}")
    symlink = "(symlink) " if target.is_symlink() else ""
    size = target.stat().st_size
    size_info = f" ({_fmt_size(size)})" if symlink else ""
    if _is_binary(target):
        return ToolResult(
            False,
            f"Cannot read binary file: {path} ({_fmt_size(size)}). "
            f"Use shell commands to inspect binary files."
        )
    content = _read_with_fallback(target, max_size=30000)
    if not content and size > 0:
        return ToolResult(False, f"Failed to decode {path} ({_fmt_size(size)}). File may be binary.")
    header = f"{symlink}{path}{size_info}"
    return ToolResult(True, f"{header}\n{content}")


def write_file(path: str, content: str, base: Path) -> ToolResult:
    target = resolve_path(path, base)
    existed = target.exists()
    if existed and _is_binary(target):
        return ToolResult(
            False,
            f"Cannot write to binary file: {path} ({_fmt_size(target.stat().st_size)}). "
            f"Use shell commands for binary files."
        )
    try:
        _atomic_write(target, content)
    except OSError as exc:
        return ToolResult(False, f"Failed to write {path}: {exc}")
    lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    verb = "Updated" if existed else "Created"
    return ToolResult(True, f"{verb} {target} ({lines} lines)")


def append_file(path: str, content: str, base: Path) -> ToolResult:
    target = resolve_path(path, base)
    existed = target.exists()
    if existed and _is_binary(target):
        return ToolResult(
            False,
            f"Cannot append to binary file: {path} ({_fmt_size(target.stat().st_size)}). "
            f"Use shell commands for binary files."
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(content)
    except OSError as exc:
        return ToolResult(False, f"Failed to append to {path}: {exc}")
    added = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    verb = "Appended to" if existed else "Created and appended to"
    return ToolResult(True, f"{verb} {target} (+{added} lines)")


def edit_file(path: str, old_str: str, new_str: str, base: Path, replace_all: bool = False) -> ToolResult:
    target = resolve_path(path, base)
    if not target.exists():
        return ToolResult(False, f"File not found: {path}")
    if not target.is_file():
        return ToolResult(False, f"Not a file (directory or special): {path}")
    if _is_binary(target):
        return ToolResult(
            False,
            f"Cannot edit binary file: {path} ({_fmt_size(target.stat().st_size)}). "
            f"Use shell commands for binary files."
        )

    content = _read_with_fallback(target)
    if not content and target.stat().st_size > 0:
        return ToolResult(False, f"Failed to decode {path}. File may be binary or corrupted.")

    if old_str not in content:
        lines = content.split("\n")
        similar = []
        search_tokens = old_str.strip().split()
        for i, line in enumerate(lines, 1):
            for token in search_tokens:
                if len(token) >= 3 and token in line:
                    similar.append(f"  Line {i}: {line[:100]}")
                    break
        hint = ""
        if similar:
            hint = f"\nSimilar lines found:\n" + "\n".join(similar[:5]) + "\n\nMake sure old_str exactly matches the file content (including whitespace)."
        else:
            hint = f"\nThe string was not found in the file. Use read_file first to see the current content."
        return ToolResult(False, f"edit_file: old_str not found in {path}.{hint}")

    if not replace_all and content.count(old_str) > 1:
        count = content.count(old_str)
        locations = []
        pos = 0
        while True:
            idx = content.find(old_str, pos)
            if idx < 0:
                break
            line_num = content[:idx].count("\n") + 1
            locations.append(line_num)
            pos = idx + 1
        return ToolResult(
            False,
            f"edit_file: old_str appears {count} times (lines {', '.join(str(l) for l in locations[:10])}"
            f"{'...' if len(locations) > 10 else ''}). "
            f"Provide more surrounding context to make it unique, or set replace_all=true."
        )

    new_content = content.replace(old_str, new_str, 1 if not replace_all else -1)
    if new_content == content:
        return ToolResult(False, f"edit_file: no changes made (old_str and new_str are identical)")

    _create_backup(target)
    try:
        _atomic_write(target, new_content)
    except OSError as exc:
        return ToolResult(False, f"Failed to write {path}: {exc}")

    old_lines = old_str.split("\n")
    new_lines = new_str.split("\n")
    diff_summary = []
    for line in old_lines[:3]:
        diff_summary.append(f"- {line}")
    if len(old_lines) > 3:
        diff_summary.append(f"- ... ({len(old_lines) - 3} more lines removed)")
    for line in new_lines[:3]:
        diff_summary.append(f"+ {line}")
    if len(new_lines) > 3:
        diff_summary.append(f"+ ... ({len(new_lines) - 3} more lines added)")

    count_text = "1 occurrence" if not replace_all else f"{content.count(old_str)} occurrences"
    return ToolResult(True, f"Edited {target} ({count_text}, backup at {target}.bak):\n" + "\n".join(diff_summary))


def move_file(src: str, dst: str, base: Path) -> ToolResult:
    source = resolve_path(src, base)
    dest = resolve_path(dst, base)
    if not source.exists():
        return ToolResult(False, f"Source not found: {src}")
    symlink = " (symlink)" if source.is_symlink() else ""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        _create_backup(dest)
    try:
        shutil.move(str(source), str(dest))
    except shutil.Error:
        try:
            shutil.copy2(str(source), str(dest))
            source.unlink()
        except OSError as exc:
            return ToolResult(False, f"Failed to move {src} -> {dst}: {exc}")
    except OSError as exc:
        return ToolResult(False, f"Failed to move {src} -> {dst}: {exc}")
    return ToolResult(True, f"Moved {source}{symlink} -> {dest}")


def search_files(query: str, base: Path) -> ToolResult:
    # Prefer ripgrep for content search, fd for filename search
    rg = shutil.which("rg")
    fd = shutil.which("fd")
    if rg:
        proc = subprocess.run(
            [rg, "-n", "--hidden", "--glob", "!*.pyc", "--glob", "!.git", query, str(base)],
            text=True, capture_output=True, timeout=30,
        )
        output = (proc.stdout + proc.stderr).strip()
        if output:
            return ToolResult(proc.returncode in (0, 1), output[:30000])
    if fd:
        proc = subprocess.run(
            [fd, "--hidden", "--glob", query, "--max-results", "200", str(base)],
            text=True, capture_output=True, timeout=15,
        )
        output = (proc.stdout + proc.stderr).strip()
        if output:
            return ToolResult(True, output[:30000])
    # Python fallback — direct content search
    matches: list[str] = []
    for path in base.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            try:
                data = path.read_text(encoding="utf-8", errors="ignore")
                if query in data:
                    matches.append(str(path))
            except OSError:
                pass
    return ToolResult(True, "\n".join(matches[:200]) or "No matches.")


def create_skill(name: str, summary: str, body: str, root: Path,
                 exec_code: str | None = None, exec_lang: str = "py") -> ToolResult:
    slug = slugify(name)
    skills_dir = root / "skills"
    skill_dir = skills_dir / slug
    builtin = _builtin_skills_dir()

    # ── Check built-in skills first ──
    if builtin.exists():
        builtin_skills = load_skills(builtin)
        for s in builtin_skills:
            if s.name == slug:
                return ToolResult(
                    False,
                    f"Built-in skill `{slug}` already exists at {s.path}\n"
                    f"  Summary: {s.summary}\n"
                    f"  Use edit_file or patch_file to customize it, "
                    f"or choose a different name."
                )

    # ── Detect existing skill with same slug in user dir ──
    if skill_dir.exists():
        existing_skills = load_skills(skills_dir)
        existing_summary = ""
        for s in existing_skills:
            if s.name == slug:
                existing_summary = s.summary
                break
        msg = f"Skill `{slug}` already exists at {skill_dir}/"
        if existing_summary:
            msg += f"\n  Existing summary: {existing_summary}"
        msg += "\n  Use edit_file or patch_file to modify it instead."
        return ToolResult(False, msg)

    # ── Fuzzy match by name ──
    existing_skills = load_skills(builtin, skills_dir)
    existing_names = [s.name for s in existing_skills]
    close_matches = difflib.get_close_matches(slug, existing_names, n=3, cutoff=0.6)
    if close_matches:
        similar = "\n".join(f"  - `{m}`" for m in close_matches)
        return ToolResult(
            False,
            f"Skill `{slug}` not created — found similar existing skills:\n{similar}\n\n"
            f"Use edit_file or patch_file to modify an existing skill, "
            f"or choose a more distinctive name."
        )

    # ── Check summary overlap ──
    summary_tokens = set(summary.lower().split())
    for s in existing_skills:
        s_tokens = set(s.summary.lower().split())
        overlap = summary_tokens & s_tokens
        if len(overlap) >= 3:
            return ToolResult(
                False,
                f"Skill `{slug}` has significant summary overlap with `{s.name}`:\n"
                f"  New summary: {summary}\n"
                f"  Existing:    {s.summary}\n\n"
                f"Use edit_file or patch_file to enhance the existing skill instead."
            )

    skill_dir.mkdir(parents=True, exist_ok=True)

    required_sections = ["## Response Examples", "## Summary", "## When To Use", "## Steps"]
    full_body = body.strip()
    if not full_body.startswith("# "):
        full_body = f"# {slug}\n\nSummary: {summary}\n\n{full_body}\n"
    for section in required_sections:
        if section not in full_body:
            full_body += (
                f"\n\n{section}\n\n"
                + (_AUTO_SECTIONS.get(section, "(fill this section)"))
            )
    (skill_dir / "SKILL.md").write_text(full_body + "\n", encoding="utf-8")

    if exec_code:
        ext = EXEC_EXT_MAP.get(exec_lang, "py")
        (skill_dir / f"exec.{ext}").write_text(exec_code.strip() + "\n", encoding="utf-8")
        if ext == "py":
            os.chmod(skill_dir / f"exec.{ext}", 0o755)

    upsert_skill(root / "memory" / "memory.md", slug, summary)
    return ToolResult(True, f"Created skill `{slug}` at {skill_dir}/SKILL.md")

_AUTO_SECTIONS = {
    "## Steps": "1. Validate input\n2. Execute logic\n3. Return structured result",
    "## Response Examples": (
        "### Agent invoca la skill\n"
        "```\n"
        "<action>run_skill</action>\n"
        "<skill>SKILL_NAME</skill>\n"
        "<args>ARGS_HERE</args>\n"
        "<timeout>30</timeout>\n"
        "```\n"
        "### Skill devuelve resultado\n"
        "```\n"
        "status: ok\n"
        "result: ...\n"
        "```\n"
    ),
    "## When To Use": "- Similar patterns or problems\n- Ad-hoc as needed",
}


def remember(note: str, root: Path) -> ToolResult:
    mem_path = root / "memory" / "memory.md"
    append_note(mem_path, note)
    return ToolResult(True, f"Saved note to {mem_path}")


def run_skill(skill: str, args: str, root: Path, cwd: Path, timeout: int = 30) -> ToolResult:
    slug = slugify(skill)
    # Try user skills first, then built-in
    skill_dirs = [root / "skills" / slug, _builtin_skills_dir() / slug]
    skill_dir = None
    for d in skill_dirs:
        if d.exists():
            skill_dir = d
            break
    if skill_dir is None:
        return ToolResult(False, f"Skill not found: {skill}")

    exec_file = None
    exec_lang = None
    for ext, lang in EXEC_EXT_MAP.items():
        candidate = skill_dir / f"exec.{ext}"
        if candidate.exists():
            exec_file = candidate
            exec_lang = lang
            break

    if exec_file is None or exec_lang is None:
        return ToolResult(False, f"Skill `{skill}` has no executable script (exec.bash, exec.py, etc.)")

    if exec_lang == "gcc":
        return _run_c_script(exec_file, args, cwd, timeout)

    runtime = RUNTIME_CMD.get(exec_lang)
    if runtime is None:
        return ToolResult(False, f"Unsupported runtime for `{skill}`: {exec_lang}")

    cmd = runtime + [str(exec_file)]
    if args.strip():
        try:
            cmd.extend(shlex.split(args.strip()))
        except ValueError:
            cmd.append(args.strip())

    env = os.environ.copy()
    env["DELUX_AGENT"] = "1"
    env["DELUX_SKILL"] = slug

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (proc.stdout + proc.stderr).strip()
        return ToolResult(proc.returncode == 0, output or f"exit code {proc.returncode}")
    except subprocess.TimeoutExpired:
        return ToolResult(False, f"Skill `{skill}` timed out after {timeout}s")
    except OSError as exc:
        return ToolResult(False, f"Failed to run skill `{skill}`: {exc}")


def _run_c_script(exec_file: Path, args: str, cwd: Path, timeout: int) -> ToolResult:
    binary = exec_file.with_suffix("")
    try:
        compile_cmd = ["gcc", "-o", str(binary), str(exec_file)]
        compile_proc = subprocess.run(compile_cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        if compile_proc.returncode != 0:
            error = (compile_proc.stdout + compile_proc.stderr).strip()
            return ToolResult(False, f"Compilation failed for `{exec_file.name}`: {error}")

        cmd = [str(binary)]
        if args.strip():
            try:
                cmd.extend(shlex.split(args.strip()))
            except ValueError:
                cmd.append(args.strip())

        env = os.environ.copy()
        env["DELUX_AGENT"] = "1"
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        output = (proc.stdout + proc.stderr).strip()
        return ToolResult(proc.returncode == 0, output or f"exit code {proc.returncode}")
    except subprocess.TimeoutExpired:
        return ToolResult(False, f"Compilation of `{exec_file.name}` timed out after {timeout}s")
    except OSError as exc:
        return ToolResult(False, f"Failed to compile `{exec_file.name}`: {exc}")
    finally:
        if binary.exists():
            try:
                binary.unlink()
            except OSError:
                pass


def view_file_paged(path: str, line_start: int = 1, line_end: int = 50, cwd: Path | None = None) -> str:
    if cwd is not None:
        target = _resolve_for_read(path, cwd)
    else:
        target = Path(path)
    if not target.exists():
        return f"ERROR: File not found: {path}"
    if not target.is_file():
        return f"ERROR: Not a file (directory or special): {path}"
    if _is_binary(target):
        return (
            f"ERROR: Cannot view binary file: {path} "
            f"({_fmt_size(target.stat().st_size)}). Use shell commands."
        )

    content = _read_with_fallback(target)
    if not content and target.stat().st_size > 0:
        return f"ERROR: Failed to decode {path}. File may be binary or corrupted."

    lines = content.splitlines(keepends=True)
    total = len(lines)

    if line_start < 1:
        line_start = 1
    if line_end > total:
        line_end = total
    if line_start > total:
        return f"ERROR: line_start ({line_start}) exceeds total lines ({total}) in {path}"

    selected = lines[line_start - 1 : line_end]
    result = "".join(selected).rstrip("\n")

    header = f"[{path} | lines {line_start}-{line_end} of {total} | {_fmt_size(target.stat().st_size)}]\n"
    if line_end < total:
        remaining = total - line_end
        header += f"[... {remaining} more lines below — use higher line_end to read]\n\n"
    if line_start > 1:
        header += f"[... {line_start - 1} lines above — use lower line_start to read]\n\n"
    return header + result


def patch_file(path: str, old_str: str, new_str: str) -> str:
    target = Path(path)
    if not target.is_absolute():
        target = Path(path).resolve()
    if not target.exists():
        return f"ERROR: File not found: {path}"
    if not target.is_file():
        return f"ERROR: Not a file (directory or special): {path}"
    if _is_binary(target):
        return (
            f"ERROR: Cannot patch binary file: {path} "
            f"({_fmt_size(target.stat().st_size)}). Use shell commands."
        )

    content = _read_with_fallback(target)
    if not content and target.stat().st_size > 0:
        return f"ERROR: Failed to decode {path}. File may be binary or corrupted."

    if old_str not in content:
        similar = []
        search_tokens = old_str.strip().split()
        for i, line in enumerate(content.split("\n"), 1):
            for token in search_tokens:
                if len(token) >= 3 and token in line:
                    similar.append(f"  Line {i}: {line[:100]}")
                    break
        hint = ""
        if similar:
            hint = "\nSimilar lines found:\n" + "\n".join(similar[:5])
        else:
            hint = "\nThe string was not found in the file."
        return (
            f"ERROR: patch_file: old_str not found in {path}.{hint}\n\n"
            f"Make sure old_str exactly matches the file content "
            f"(including whitespace). Use view_file to see current content."
        )

    count = content.count(old_str)
    if count > 1:
        locations = []
        pos = 0
        while True:
            idx = content.find(old_str, pos)
            if idx < 0:
                break
            line_num = content[:idx].count("\n") + 1
            locations.append(line_num)
            pos = idx + 1
        return (
            f"ERROR: patch_file: old_str appears {count} times (lines "
            f"{', '.join(str(l) for l in locations[:10])}"
            f"{'...' if len(locations) > 10 else ''}). "
            f"Provide more surrounding context to make the match unique."
        )

    new_content = content.replace(old_str, new_str, 1)
    if new_content == content:
        return "ERROR: patch_file: no changes made (old_str and new_str are identical)"

    _create_backup(target)
    try:
        _atomic_write(target, new_content)
    except OSError as exc:
        return f"ERROR: Failed to write {path}: {exc}"

    old_lines = old_str.split("\n")
    new_lines = new_str.split("\n")
    diff = []
    for line in old_lines[:3]:
        diff.append(f"- {line}")
    if len(old_lines) > 3:
        diff.append(f"- ... ({len(old_lines) - 3} more lines removed)")
    for line in new_lines[:3]:
        diff.append(f"+ {line}")
    if len(new_lines) > 3:
        diff.append(f"+ ... ({len(new_lines) - 3} more lines added)")

    return "SUCCESS: Edited " + str(target) + " (backup at " + str(target) + ".bak)\n" + "\n".join(diff)


def execute_command_secure(cmd: str, timeout: int = 15) -> str:
    proc = None
    try:
        env = os.environ.copy()
        env["DELUX_AGENT"] = "1"
        env["TERM"] = "dumb"
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        stdout, _ = proc.communicate(timeout=timeout)
        output = stdout.decode("utf-8", errors="replace").strip()
        output = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', output)
        output = re.sub(r'\x1b\([0-9A-Za-z]', '', output)
        if proc.returncode != 0:
            return f"ERROR: Command failed (exit code {proc.returncode}): {output}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        if proc:
            proc.kill()
            proc.wait()
        return (
            "ERROR: Command timed out — execution exceeded "
            f"{timeout}s limit. For long-running commands, "
            "consider using shell background mode (&) or increasing timeout."
        )
    except OSError as exc:
        return f"ERROR: Failed to execute command: {exc}"


def search_web(query: str, top_k: int = 5) -> str:
    ddgr = shutil.which("ddgr")
    if ddgr:
        try:
            proc = subprocess.run(
                [ddgr, "--json", "-n", str(top_k), query],
                capture_output=True, text=True, timeout=15,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                import json
                data = json.loads(proc.stdout)
                lines = [f"### Web Search Results for: '{query}'\n"]
                for i, item in enumerate(data[:top_k], 1):
                    title = item.get("title", "No Title")
                    url = item.get("url", "#")
                    abstract = item.get("abstract", "")
                    lines.append(f"{i}. **{title}**")
                    lines.append(f"   URL: {url}")
                    if abstract:
                        lines.append(f"   {abstract}")
                    lines.append("")
                return "\n".join(lines)
        except Exception:
            pass

    import urllib.request
    import urllib.parse
    try:
        url = f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Delux-Agent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        import re as _re
        results = _re.findall(
            r'<a[^>]*href="([^"]+)"[^>]*class="result-link"[^>]*>(.*?)</a>',
            html,
        )
        if results:
            lines = [f"### Web Results for: '{query}'\n"]
            for i, (url_href, title) in enumerate(results[:top_k], 1):
                lines.append(f"{i}. **{_re.sub(r'<[^>]+>', '', title).strip()}**")
                lines.append(f"   {url_href}")
                lines.append("")
            return "\n".join(lines)
        return f"ERROR: No web results for '{query}'"
    except Exception as exc:
        return f"ERROR: Web search failed: {exc}"


_VERIFIERS: dict[str, list[str]] = {
    ".py": ["python3", "-c", "import ast, sys; ast.parse(open(sys.argv[1]).read()); print('OK')", "--"],
    ".sh": ["bash", "-n"],
    ".bash": ["bash", "-n"],
    ".zsh": ["zsh", "-n"],
    ".js": ["node", "--check"],
    ".mjs": ["node", "--check"],
    ".ts": ["npx", "--yes", "tsc", "--noEmit"],
    ".json": ["python3", "-c", "import json, sys; json.load(open(sys.argv[1])); print('OK')", "--"],
    ".yaml": ["python3", "-c",
              "try:\n import yaml\nexcept ImportError:\n import json, sys; sys.exit(0)\n"
              "with open(sys.argv[1]) as f: yaml.safe_load(f); print('OK')", "--"],
    ".yml": ["python3", "-c",
             "try:\n import yaml\nexcept ImportError:\n import json, sys; sys.exit(0)\n"
             "with open(sys.argv[1]) as f: yaml.safe_load(f); print('OK')", "--"],
    ".c": ["gcc", "-fsyntax-only"],
    ".cpp": ["g++", "-fsyntax-only"],
    ".cc": ["g++", "-fsyntax-only"],
    ".cxx": ["g++", "-fsyntax-only"],
    ".go": ["go", "vet"],
    ".rs": ["rustc", "--edition", "2021", "--crate-type", "lib"],
    ".toml": ["python3", "-c",
              "import sys\n"
              "try:\n import tomllib\nexcept ImportError:\n"
              " try:\n  import tomli as tomllib\n"
              " except ImportError:\n  sys.exit(0)\n"
              "with open(sys.argv[1],'rb') as f: tomllib.load(f); print('OK')", "--"],
    ".html": ["python3", "-c",
              "import sys\ntry:\n from html.parser import HTMLParser\n"
              " p=HTMLParser()\n p.feed(open(sys.argv[1]).read()); p.close(); print('OK')\n"
              "except Exception as e: print(f'ERROR:{e}'); sys.exit(1)", "--"],
    ".css": ["python3", "-c",
             "import sys\ntry:\n import cssutils\nexcept ImportError:\n sys.exit(0)\n"
             "cssutils.parseFile(sys.argv[1]); print('OK')", "--"],
    ".xml": ["python3", "-c",
             "import sys, xml.etree.ElementTree as ET\ntry:\n ET.parse(sys.argv[1]); print('OK')\n"
             "except Exception as e: print(f'ERROR:{e}'); sys.exit(1)", "--"],
}


def verify_file(path: str, base: Path) -> str:
    target = resolve_path(path, base)
    if not target.exists():
        return f"ERROR: File not found: {path}"
    if not target.is_file():
        return f"ERROR: Not a file: {path}"
    ext = target.suffix.lower()
    cmd_template = _VERIFIERS.get(ext)
    if cmd_template is None:
        return f"SUCCESS: No built-in verifier for {ext}. Run a manual test."
    cmd = [a.replace("--", str(target)) for a in cmd_template]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0:
            out = proc.stdout.strip()[:200]
            return f"SUCCESS: {path} passed {ext} check. {out}".strip()
        error = proc.stderr.strip()[:500] or proc.stdout.strip()[:500]
        return f"ERROR: {path} FAILED {ext} check:\n{error}"
    except subprocess.TimeoutExpired:
        return f"ERROR: Verification timed out for {path}"
    except FileNotFoundError:
        return f"ERROR: Verifier not found for {ext} (need compiler/interpreter)"
    except OSError as exc:
        return f"ERROR: Verification failed: {exc}"


def call_mcp_tool(server_name: str, tool_name: str, arguments: dict, root: Path, timeout: int = 30) -> ToolResult:
    from .mcp_client import MCPClient
    from .mcp_store import get_enabled_servers, MCPServerEntry

    servers = {s.name: s for s in get_enabled_servers(root)}
    if server_name not in servers:
        return ToolResult(False, f"MCP server not found: {server_name}. Use /mcp to see available servers.")

    s = servers[server_name]
    try:
        client = MCPClient(s.name, s.command, s.args, s.env or None)
        client.start()
        client.initialize()
        result = client.call_tool(tool_name, arguments)
        client.stop()
        return ToolResult(not result.startswith("ERROR:"), result)
    except Exception as exc:
        return ToolResult(False, f"MCP error calling {server_name}/{tool_name}: {exc}")


def discover_mcp_tools(server_name: str, root: Path) -> ToolResult:
    from .mcp_client import MCPClient
    from .mcp_store import get_enabled_servers, cache_tools, discover_tools

    try:
        all_tools = discover_tools(root, server_name)
        cache_tools(root, all_tools)
        lines = []
        for srv, tools in all_tools.items():
            lines.append(f"Server: {srv}")
            for t in tools:
                if t.name == "error":
                    lines.append(f"  (error: {t.description})")
                else:
                    lines.append(f"  - {t.name}: {t.description}")
        return ToolResult(True, "\n".join(lines))
    except Exception as exc:
        return ToolResult(False, f"Failed to discover MCP tools: {exc}")


# ── Browser tools ──────────────────────────────────────────────────────

def browser_navigate(url: str, timeout: int = 30, headed: bool = False) -> ToolResult:
    from .browser import get_browser
    try:
        result = get_browser(headed=headed).navigate(url, timeout=timeout)
        return ToolResult(result.ok, result.output)
    except RuntimeError as e:
        return ToolResult(False, str(e))


def browser_click(selector: str, headed: bool = False) -> ToolResult:
    from .browser import get_browser
    try:
        result = get_browser(headed=headed).click(selector)
        return ToolResult(result.ok, result.output)
    except RuntimeError as e:
        return ToolResult(False, str(e))


def browser_type(selector: str, text: str, headed: bool = False) -> ToolResult:
    from .browser import get_browser
    try:
        result = get_browser(headed=headed).type(selector, text)
        return ToolResult(result.ok, result.output)
    except RuntimeError as e:
        return ToolResult(False, str(e))


def browser_scroll(direction: str = "down", amount: int = 500, headed: bool = False) -> ToolResult:
    from .browser import get_browser
    try:
        result = get_browser(headed=headed).scroll(direction, amount)
        return ToolResult(result.ok, result.output)
    except RuntimeError as e:
        return ToolResult(False, str(e))


def browser_snapshot(headed: bool = False) -> ToolResult:
    from .browser import get_browser
    try:
        result = get_browser(headed=headed).snapshot()
        return ToolResult(result.ok, result.output)
    except RuntimeError as e:
        return ToolResult(False, str(e))


def browser_back(headed: bool = False) -> ToolResult:
    from .browser import get_browser
    try:
        result = get_browser(headed=headed).back()
        return ToolResult(result.ok, result.output)
    except RuntimeError as e:
        return ToolResult(False, str(e))


def browser_screenshot(full_page: bool = False, headed: bool = False) -> ToolResult:
    from .browser import get_browser
    try:
        result = get_browser(headed=headed).screenshot(full_page=full_page)
        return ToolResult(result.ok, result.output)
    except RuntimeError as e:
        return ToolResult(False, str(e))


def browser_extract(headed: bool = False) -> ToolResult:
    from .browser import get_browser
    try:
        result = get_browser(headed=headed).extract_text()
        return ToolResult(result.ok, result.output)
    except RuntimeError as e:
        return ToolResult(False, str(e))


def browser_close() -> ToolResult:
    from .browser import close_browser
    close_browser()
    return ToolResult(True, "Browser closed")


# ── Vision tools ───────────────────────────────────────────────────────

def vision_analyze(image_path: str, prompt: str, api_base: str = "", api_key: str | None = None, model: str = "", api_endpoint: str | None = None) -> ToolResult:
    from .vision import analyze_image
    result = analyze_image(image_path, prompt, api_base, api_key, model, api_endpoint)
    return ToolResult(result.ok, result.output)


# ── Subagent tools ─────────────────────────────────────────────────────

def delegate_task(task: str, root: Path, cwd: Path, max_steps: int = 12, timeout: int = 120) -> ToolResult:
    from .subagent import spawn_subagent
    result = spawn_subagent(
        task=task,
        config_root=str(root),
        cwd=str(cwd),
        max_steps=max_steps,
        timeout=timeout,
    )
    return ToolResult(result.ok, result.output)


# ── Cron tools ─────────────────────────────────────────────────────────

def cron_add(name: str, expression: str, command: str, root: Path) -> ToolResult:
    from .cron import get_scheduler
    result = get_scheduler(root).add(name, expression, command)
    return ToolResult(result.ok, result.output)


def cron_remove(job_id: int, root: Path) -> ToolResult:
    from .cron import get_scheduler
    result = get_scheduler(root).remove(job_id)
    return ToolResult(result.ok, result.output)


def cron_list(root: Path) -> ToolResult:
    from .cron import get_scheduler
    jobs = get_scheduler(root).list_jobs()
    if not jobs:
        return ToolResult(True, "No cron jobs configured.")
    lines = []
    for j in jobs:
        status = "ON" if j.enabled else "OFF"
        lines.append(f"  [{j.id}] {status} {j.name}: {j.expression} -> {j.command}")
        if j.last_run:
            lines.append(f"       last: {j.last_run}")
    return ToolResult(True, "\n".join(lines))


def cron_enable(job_id: int, enabled: bool, root: Path) -> ToolResult:
    from .cron import get_scheduler
    result = get_scheduler(root).enable(job_id, enabled)
    return ToolResult(result.ok, result.output)


def cron_run(job_id: int, root: Path, timeout: int = 60) -> ToolResult:
    from .cron import get_scheduler
    result = get_scheduler(root).run_now(job_id, timeout=timeout)
    return ToolResult(result.ok, f"Job {job_id} executed:\n{result.output}")


def cron_logs(job_id: int, root: Path) -> ToolResult:
    from .cron import get_scheduler
    output = get_scheduler(root).logs(job_id)
    return ToolResult(True, output)


# ── Kanban tools ───────────────────────────────────────────────────────

def kanban_add(title: str, description: str, root: Path, tags: str = "", priority: int = 0) -> ToolResult:
    from .kanban import get_board
    result = get_board(root).add(title, description, tags, priority)
    return ToolResult(result.ok, result.output)


def kanban_list(root: Path, status: str | None = None) -> ToolResult:
    from .kanban import get_board
    output = get_board(root).list(status)
    return ToolResult(True, output)


def kanban_move(card_id: int, status: str, root: Path) -> ToolResult:
    from .kanban import get_board
    result = get_board(root).move(card_id, status)
    return ToolResult(result.ok, result.output)


def kanban_show(card_id: int, root: Path) -> ToolResult:
    from .kanban import get_board
    output = get_board(root).show(card_id)
    return ToolResult(True, output)


def kanban_delete(card_id: int, root: Path) -> ToolResult:
    from .kanban import get_board
    result = get_board(root).delete(card_id)
    return ToolResult(result.ok, result.output)


def kanban_update(card_id: int, root: Path, **kwargs) -> ToolResult:
    from .kanban import get_board
    result = get_board(root).update(card_id, **kwargs)
    return ToolResult(result.ok, result.output)


# ── Computer Use tools ─────────────────────────────────────────────────

def computer_screenshot(root: Path) -> ToolResult:
    from .computer_use import screenshot
    output_dir = str(root / "screenshots")
    result = screenshot(output_dir=output_dir)
    return ToolResult(result.ok, result.output)


def computer_click(x: int, y: int, button: str = "left") -> ToolResult:
    from .computer_use import click
    result = click(x, y, button)
    return ToolResult(result.ok, result.output)


def computer_type(text: str) -> ToolResult:
    from .computer_use import type_text
    result = type_text(text)
    return ToolResult(result.ok, result.output)


def computer_keypress(key: str) -> ToolResult:
    from .computer_use import keypress
    result = keypress(key)
    return ToolResult(result.ok, result.output)


def computer_size() -> ToolResult:
    from .computer_use import get_screen_size
    result = get_screen_size()
    return ToolResult(result.ok, result.output)
