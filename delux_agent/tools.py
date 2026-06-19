from __future__ import annotations

import difflib
import os
import re
import selectors
import shlex
import shutil
import subprocess
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
    target = Path(path)
    if not target.is_absolute():
        target = (base / target).resolve()
    else:
        target = target.resolve()
    if not target.exists() or not target.is_file():
        return ToolResult(False, f"File not found: {path}")
    return ToolResult(True, target.read_text(encoding="utf-8", errors="replace")[:30000])


def write_file(path: str, content: str, base: Path) -> ToolResult:
    target = Path(path)
    if not target.is_absolute():
        target = (base / target).resolve()
    else:
        target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return ToolResult(True, f"Wrote {target}")


def append_file(path: str, content: str, base: Path) -> ToolResult:
    target = Path(path)
    if not target.is_absolute():
        target = (base / target).resolve()
    else:
        target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(content)
    return ToolResult(True, f"Appended {target}")


def edit_file(path: str, old_str: str, new_str: str, base: Path, replace_all: bool = False) -> ToolResult:
    target = Path(path)
    if not target.is_absolute():
        target = (base / target).resolve()
    else:
        target = target.resolve()
    if not target.exists() or not target.is_file():
        return ToolResult(False, f"File not found: {path}")

    content = target.read_text(encoding="utf-8")

    if old_str not in content:
        # Try to find closest match and give helpful context
        lines = content.split("\n")
        similar = []
        old_stripped = old_str.strip()
        search_tokens = old_stripped.split()
        for i, line in enumerate(lines, 1):
            # Check if any significant token from old_str appears in the line
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
        # Count occurrences to help user
        count = content.count(old_str)
        # Find line numbers of each occurrence
        lines = content.split("\n")
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
            f"edit_file: old_str appears {count} times (lines {', '.join(str(l) for l in locations)}). "
            f"Provide more surrounding context to make it unique, or set replace_all=true."
        )

    new_content = content.replace(old_str, new_str, 1 if not replace_all else -1)
    if new_content == content:
        return ToolResult(False, f"edit_file: no changes made (old_str and new_str are identical)")

    target.write_text(new_content, encoding="utf-8")

    # Build a minimal diff summary
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
    return ToolResult(True, f"Edited {target} ({count_text}):\n" + "\n".join(diff_summary))


def move_file(src: str, dst: str, base: Path) -> ToolResult:
    source = Path(src)
    dest = Path(dst)
    if not source.is_absolute():
        source = (base / source).resolve()
    else:
        source = source.resolve()
    if not dest.is_absolute():
        dest = (base / dest).resolve()
    else:
        dest = dest.resolve()
    if not source.exists():
        return ToolResult(False, f"Source not found: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(dest))
    return ToolResult(True, f"Moved {source} -> {dest}")


def search_files(query: str, base: Path) -> ToolResult:
    rg = shutil.which("rg")
    if rg:
        proc = subprocess.run([rg, "-n", "--hidden", "--glob", "!*.pyc", query, str(base)], text=True, capture_output=True)
        output = (proc.stdout + proc.stderr).strip()
        return ToolResult(proc.returncode in (0, 1), output[:30000] or "No matches.")
    matches: list[str] = []
    for path in base.rglob("*"):
        if path.is_file():
            data = path.read_text(encoding="utf-8", errors="ignore")
            if query in data:
                matches.append(str(path))
    return ToolResult(True, "\n".join(matches) or "No matches.")


def create_skill(name: str, summary: str, body: str, root: Path,
                 exec_code: str | None = None, exec_lang: str = "py") -> ToolResult:
    slug = slugify(name)
    skills_dir = root / "skills"
    skill_dir = skills_dir / slug

    # ── Detect existing skill with same slug ──
    if skill_dir.exists():
        existing_skills = load_skills(skills_dir)
        existing_summary = ""
        for s in existing_skills:
            if s.name == slug:
                existing_summary = s.summary
                break
        msg = f"Skill `{slug}` already exists at skills/{slug}/"
        if existing_summary:
            msg += f"\n  Existing summary: {existing_summary}"
        msg += "\n  Use edit_file or patch_file to modify it instead."
        return ToolResult(False, msg)

    # ── Fuzzy match by name ──
    existing_skills = load_skills(skills_dir)
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
    return ToolResult(True, f"Created skill `{slug}` at skills/{slug}/SKILL.md")

_AUTO_SECTIONS = {
    "## Steps": "1. Validate input\n2. Execute logic\n3. Return JSON result",
    "## Response Examples": (
        "### Agent invoca la skill\n"
        '```json\n{"action":"run_skill","skill":"<name>","args":"<args>","timeout":30}\n```\n'
        "### Skill devuelve resultado\n"
        '```json\n{"status":"ok","result":"..."}\n```'
    ),
    "## When To Use": "- Similar patterns or problems\n- Ad-hoc as needed",
}


def remember(note: str, root: Path) -> ToolResult:
    append_note(root / "memory" / "memory.md", note)
    return ToolResult(True, "Saved note to memory/memory.md")


def run_skill(skill: str, args: str, root: Path, cwd: Path, timeout: int = 30) -> ToolResult:
    slug = slugify(skill)
    skill_dir = root / "skills" / slug
    if not skill_dir.exists():
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


def view_file_paged(path: str, line_start: int = 1, line_end: int = 50) -> str:
    target = Path(path)
    if not target.exists():
        return f"ERROR: File not found: {path}"
    if not target.is_file():
        return f"ERROR: Not a file: {path}"
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        return f"ERROR: Permission denied: {path}"
    except OSError as exc:
        return f"ERROR: Failed to read {path}: {exc}"

    lines = text.splitlines(keepends=True)
    total = len(lines)

    if line_start < 1:
        line_start = 1
    if line_end > total:
        line_end = total
    if line_start > total:
        return (
            f"ERROR: line_start ({line_start}) exceeds total lines "
            f"({total}) in {path}"
        )

    selected = lines[line_start - 1 : line_end]
    result = "".join(selected).rstrip("\n")

    if line_end < total:
        remaining = total - line_end
        result += (
            "\n[CONSOLA: Archivo truncado. Quedan "
            f"{remaining} líneas más por leer. "
            "Usa rangos superiores si lo necesitas]"
        )
    return result


def patch_file(path: str, old_str: str, new_str: str) -> str:
    target = Path(path)
    if not target.exists():
        return f"ERROR: File not found: {path}"
    if not target.is_file():
        return f"ERROR: Not a file: {path}"

    try:
        content = target.read_text(encoding="utf-8")
    except PermissionError:
        return f"ERROR: Permission denied: {path}"
    except OSError as exc:
        return f"ERROR: Failed to read {path}: {exc}"

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
            f"{', '.join(str(l) for l in locations)}). "
            f"Provide more surrounding context to make the match unique."
        )

    new_content = content.replace(old_str, new_str, 1)
    if new_content == content:
        return "ERROR: patch_file: no changes made (old_str and new_str are identical)"

    try:
        target.write_text(new_content, encoding="utf-8")
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

    return "SUCCESS: Edited " + str(target) + "\n" + "\n".join(diff)


def execute_command_secure(cmd: str, timeout: int = 15) -> str:
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        stdout, _ = proc.communicate(timeout=timeout)
        output = stdout.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            return f"ERROR: Command failed (exit code {proc.returncode}): {output}"
        return output
    except subprocess.TimeoutExpired:
        if proc:
            proc.kill()
            proc.wait()
        return (
            "ERROR: [ERROR de la Consola Delux: El comando tardó demasiado "
            "y fue cancelado automáticamente para evitar bloqueos. "
            "Si es un servidor, córrelo en segundo plano o revisa si hay bucles infinitos]"
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
    ".js": ["node", "--check"],
    ".json": ["python3", "-c", "import json, sys; json.load(open(sys.argv[1])); print('OK')", "--"],
    ".yaml": ["python3", "-c", "import json, sys; print('syntax check skipped (no pyyaml)')", "--"],
    ".yml": ["python3", "-c", "import json, sys; print('syntax check skipped (no pyyaml)')", "--"],
    ".c": ["gcc", "-fsyntax-only"],
    ".cpp": ["g++", "-fsyntax-only"],
    ".go": ["go", "vet"],
    ".rs": ["rustc", "--edition", "2021", "--crate-type", "lib"],
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
