from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


DEFAULT_MEMORY = """# Delux Agent Memory

## Profile
- Shell: fish-first.
- Safety: never use sudo, su, doas, pkexec, or privilege escalation.

## Skills

## Notes
"""

DEFAULT_DOCS_README = """# Docs

Add Markdown documentation here. Delux loads every `*.md` file under this directory into its context.
"""

DEFAULT_SKILLS_README = """# Skills

Each skill is an extension in its own directory:

```text
skills/change-wallpaper/SKILL.md
```
"""

DEFAULT_TESTING_README = """# Testing Workspace

This is the agent's sandbox for experiments, scripts, and intermediate files.

- All shell commands executed by the agent run with this as the working directory.
- Test scripts, downloads, and generated files are created here first.
- Useful files are moved to their final destination when the task is complete.
- Files here may be cleaned up between sessions.
"""


EXEC_EXT_MAP = {
    "bash": "bash",
    "fish": "fish",
    "sh": "bash",
    "py": "python3",
    "go": "go",
    "c": "gcc",
    "js": "node",
    "rb": "ruby",
    "rs": "rust",
}


@dataclass(frozen=True)
class Skill:
    name: str
    path: Path
    summary: str
    body: str
    has_exec: bool = False
    exec_lang: str = ""
    builtin: bool = False


def ensure_workspace(root: Path) -> None:
    (root / "memory").mkdir(parents=True, exist_ok=True)
    (root / "skills").mkdir(parents=True, exist_ok=True)
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "sessions").mkdir(parents=True, exist_ok=True)
    (root / "testing").mkdir(parents=True, exist_ok=True)
    testing_readme = root / "testing" / "README.md"
    if not testing_readme.exists():
        testing_readme.write_text(DEFAULT_TESTING_README, encoding="utf-8")
    memory_file = root / "memory" / "memory.md"
    if not memory_file.exists():
        memory_file.write_text(DEFAULT_MEMORY, encoding="utf-8")
    docs_readme = root / "docs" / "README.md"
    if not docs_readme.exists():
        docs_readme.write_text(DEFAULT_DOCS_README, encoding="utf-8")
    skills_readme = root / "skills" / "README.md"
    if not skills_readme.exists():
        skills_readme.write_text(DEFAULT_SKILLS_README, encoding="utf-8")


def read_text(path: Path, limit: int = 20000) -> str:
    data = path.read_text(encoding="utf-8", errors="replace")
    if len(data) > limit:
        return data[:limit] + "\n\n[truncated]\n"
    return data


def slugify(name: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return value or "skill"


def load_memory(memory_file: Path) -> str:
    return read_text(memory_file) if memory_file.exists() else DEFAULT_MEMORY


def load_docs(docs_dir: Path, limit_per_file: int = 12000, max_file_size: int = 51200) -> str:
    if not docs_dir.exists():
        return ""
    skip_names = {"training_examples", "few_shot_examples", "examples"}
    chunks: list[str] = []
    for path in sorted(docs_dir.rglob("*.md")):
        if path.name.lower().startswith("changelog"):
            continue
        stem = path.stem.lower()
        if any(s in stem for s in skip_names):
            continue
        if path.stat().st_size > max_file_size:
            continue
        chunks.append(f"--- {path.name} ---\n{read_text(path, limit_per_file)}")
    return "\n\n".join(chunks)


def _detect_exec_lang(skill_dir: Path) -> str:
    for ext, lang in EXEC_EXT_MAP.items():
        if (skill_dir / f"exec.{ext}").exists():
            return lang
    return ""


def sync_builtin_skills(builtin_dir: Path, user_dir: Path) -> None:
    """Copy built-in skill files to user skills dir so view_file skills/<name>/SKILL.md works."""
    if not builtin_dir.exists() or not user_dir.exists():
        return
    for skill_dir in builtin_dir.iterdir():
        if not skill_dir.is_dir():
            continue
        src_md = skill_dir / "SKILL.md"
        if not src_md.exists():
            continue
        target_dir = user_dir / skill_dir.name
        target_dir.mkdir(parents=True, exist_ok=True)
        dst_md = target_dir / "SKILL.md"
        if not dst_md.exists():
            shutil.copy2(src_md, dst_md)
        for src_exec in skill_dir.glob("exec.*"):
            dst_exec = target_dir / src_exec.name
            if not dst_exec.exists():
                shutil.copy2(src_exec, dst_exec)
                if src_exec.suffix in (".py", ".sh", ".bash", ".fish"):
                    dst_exec.chmod(0o755)


def load_skills(*skills_dirs: Path) -> list[Skill]:
    seen: set[str] = set()
    builtin_skills: list[Skill] = []
    user_skills: list[Skill] = []

    # Sync built-in skills to user dir on first access
    if len(skills_dirs) >= 2 and skills_dirs[0].exists():
        sync_builtin_skills(skills_dirs[0], skills_dirs[1])

    # User dirs (index >= 1) processed first — they have priority over built-in
    for skills_dir in skills_dirs[1:]:
        if not skills_dir.exists():
            continue
        for path in sorted(skills_dir.glob("*/SKILL.md")):
            name = path.parent.name
            if name in seen:
                continue
            seen.add(name)
            body = read_text(path, 16000)
            summary = ""
            for line in body.splitlines():
                if line.lower().startswith("summary:"):
                    summary = line.split(":", 1)[1].strip()
                    break
            skill_dir = path.parent
            exec_lang = _detect_exec_lang(skill_dir)
            user_skills.append(Skill(
                name=name,
                path=path,
                summary=summary,
                body=body,
                has_exec=bool(exec_lang),
                exec_lang=exec_lang,
                builtin=False,
            ))

    # Builtin dir (index 0) — skip names already overridden by user
    if skills_dirs and skills_dirs[0].exists():
        for path in sorted(skills_dirs[0].glob("*/SKILL.md")):
            name = path.parent.name
            if name in seen:
                continue
            seen.add(name)
            body = read_text(path, 16000)
            summary = ""
            for line in body.splitlines():
                if line.lower().startswith("summary:"):
                    summary = line.split(":", 1)[1].strip()
                    break
            skill_dir = path.parent
            exec_lang = _detect_exec_lang(skill_dir)
            builtin_skills.append(Skill(
                name=name,
                path=path,
                summary=summary,
                body=body,
                has_exec=bool(exec_lang),
                exec_lang=exec_lang,
                builtin=True,
            ))

    return builtin_skills + user_skills


def upsert_skill(memory_file: Path, name: str, summary: str) -> None:
    memory = load_memory(memory_file)
    bullet = f"- `{name}`: {summary}"
    lines = memory.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"- `{name}`:"):
            lines[i] = bullet
            memory_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    try:
        idx = lines.index("## Skills") + 1
    except ValueError:
        lines.extend(["", "## Skills"])
        idx = len(lines)
    lines.insert(idx, bullet)
    memory_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_note(memory_file: Path, note: str) -> None:
    memory = load_memory(memory_file)
    addition = f"\n- {note.strip()}\n"
    if "## Notes" in memory:
        memory = memory.replace("## Notes", "## Notes" + addition, 1)
    else:
        memory += "\n## Notes" + addition
    memory_file.write_text(memory, encoding="utf-8")


def save_session_markdown(sessions_dir: Path, title: str, content: str) -> Path:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = slugify(title)[:48] or "session"
    path = sessions_dir / f"{stamp}-{name}.md"
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return path


PENDING_TASK_FILENAME = "pending_task"


def save_pending_task(root: Path, prompt: str) -> None:
    """Save the original prompt as a pending task (execution was interrupted)."""
    path = root / PENDING_TASK_FILENAME
    path.write_text(prompt.strip(), encoding="utf-8")


def clear_pending_task(root: Path) -> None:
    """Remove pending task file (execution completed successfully)."""
    path = root / PENDING_TASK_FILENAME
    if path.exists():
        path.unlink()


def load_pending_task(root: Path) -> str | None:
    """Return the stored prompt if a pending task exists, else None."""
    path = root / PENDING_TASK_FILENAME
    if path.exists():
        content = path.read_text(encoding="utf-8").strip()
        return content if content else None
    return None
