from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .agent import Agent
from .config import default_root, load_config
from .store import ensure_workspace, load_docs, load_memory, load_skills

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"
BLUE = "\033[34m"
GRAY = "\033[38;5;245m"
RESET = "\033[0m"


def _hl(label: str, color: str = "", detail: str = "") -> str:
    """Format a highlighted action line."""
    c = color or DIM
    if detail:
        return f"  {c}·{RESET} {c}{label}{RESET}  {DIM}{detail}{RESET}"
    return f"  {c}·{RESET} {c}{label}{RESET}"


def _ok(msg: str) -> str:
    return f"  {GREEN}✓{RESET}  {DIM}{msg}{RESET}"


def _fail(msg: str) -> str:
    return f"  {RED}✗{RESET}  {RED}{msg}{RESET}"


_ACTION_ICONS = {
    "shell": "shell", "shell_secure": "shell",
    "read_file": "read", "view_file": "view",
    "write_file": "write", "append_file": "append",
    "edit_file": "edit", "patch_file": "patch",
    "verify_file": "verify",
    "search_files": "search", "search_web": "search",
    "rag_query": "rag", "rag_index": "index",
    "create_skill": "skill", "run_skill": "skill",
    "save_experience": "save", "load_experience": "load",
    "remember": "remember", "move_file": "move",
    "final": "done",
    "browser_navigate": "globe", "browser_click": "click",
    "browser_type": "type", "browser_scroll": "scroll",
    "browser_snapshot": "view", "browser_screenshot": "camera",
    "browser_extract": "extract", "browser_back": "back",
    "browser_close": "close",
    "vision_analyze": "eye",
    "delegate_task": "delegate",
    "cron_add": "cron+", "cron_remove": "cron-", "cron_list": "cron",
    "cron_enable": "cron", "cron_run": "cron>", "cron_logs": "cron",
    "kanban_add": "kanban+", "kanban_list": "kanban",
    "kanban_move": "kanban>", "kanban_show": "kanban",
    "kanban_delete": "kanban-", "kanban_update": "kanban~",
    "computer_screenshot": "screen", "computer_click": "cursor",
    "computer_type": "kb", "computer_keypress": "kb",
    "computer_size": "screen",
}

_ACTION_COLORS = {
    "shell": GREEN, "shell_secure": GREEN,
    "read_file": CYAN, "view_file": CYAN,
    "write_file": CYAN, "append_file": CYAN,
    "edit_file": YELLOW, "patch_file": YELLOW,
    "verify_file": CYAN,
    "search_files": CYAN, "search_web": CYAN,
    "rag_query": MAGENTA, "rag_index": MAGENTA,
    "create_skill": MAGENTA, "run_skill": YELLOW,
    "save_experience": DIM, "load_experience": DIM,
    "remember": DIM, "move_file": CYAN,
    "final": GREEN,
    "browser_navigate": BLUE, "browser_click": BLUE,
    "browser_type": BLUE, "browser_scroll": BLUE,
    "browser_snapshot": CYAN, "browser_screenshot": CYAN,
    "browser_extract": CYAN, "browser_back": BLUE,
    "browser_close": DIM,
    "vision_analyze": MAGENTA,
    "delegate_task": YELLOW,
    "cron_add": MAGENTA, "cron_remove": MAGENTA, "cron_list": MAGENTA,
    "cron_enable": MAGENTA, "cron_run": MAGENTA, "cron_logs": MAGENTA,
    "kanban_add": YELLOW, "kanban_list": YELLOW,
    "kanban_move": YELLOW, "kanban_show": YELLOW,
    "kanban_delete": YELLOW, "kanban_update": YELLOW,
    "computer_screenshot": CYAN, "computer_click": CYAN,
    "computer_type": CYAN, "computer_keypress": CYAN,
    "computer_size": CYAN,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="delux", description="Fish-first autonomous shell agent.")
    parser.add_argument("prompt", nargs="*", help="Task for the agent.")
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory for shell commands.")
    parser.add_argument("--home", default=None, help="DELUX_HOME workspace. Defaults to ~/.delux or env.")
    parser.add_argument("--max-steps", type=int, default=12, help="Maximum autonomous action steps.")
    parser.add_argument("--quiet", action="store_true", help="Only print the final answer.")
    parser.add_argument("--init", action="store_true", help="Create memory, docs, and skills directories.")
    parser.add_argument("--context", action="store_true", help="Print loaded memory, skills, and docs context.")
    parser.add_argument("--new-skill", default=None, help="Create a blank user-editable skill.")
    parser.add_argument("--summary", default="", help="Summary used with --new-skill.")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "setup":
        setup_parser = argparse.ArgumentParser(prog="delux setup", description="Configure Delux providers and models.")
        setup_parser.add_argument("--home", default=None, help="DELUX_HOME workspace. Defaults to ~/.delux or env.")
        setup_args = setup_parser.parse_args(argv[1:])
        root = Path(setup_args.home).expanduser().resolve() if setup_args.home else default_root()
        from .wizard import run_setup

        return run_setup(root)
    if argv and argv[0] == "dataset-import":
        ds_parser = argparse.ArgumentParser(prog="delux dataset-import", description="Import agent trajectory datasets into the Dataset RAG.")
        ds_parser.add_argument("--home", default=None, help="DELUX_HOME workspace. Defaults to ~/.delux or env.")
        ds_parser.add_argument("--glaive", action="store_true", help="Also import Glaive function-calling dataset")
        ds_args = ds_parser.parse_args(argv[1:])
        root = Path(ds_args.home).expanduser().resolve() if ds_args.home else default_root()
        from .dataset_rag import DatasetRAG
        project_root = Path(__file__).resolve().parent.parent
        ds = DatasetRAG(root)
        total = 0
        paths = [
            (project_root / "dataset_hermes" / "data" / "kimi" / "train.parquet", DatasetRAG.SOURCE_HERMES_KIMI),
            (project_root / "dataset_hermes" / "data" / "glm-5.1" / "train.parquet", DatasetRAG.SOURCE_HERMES_GLM),
            (project_root / "dataset_multiturn" / "data" / "train-00000-of-00001.parquet", DatasetRAG.SOURCE_MULTITURN),
        ]
        for p, src in paths:
            if p.exists():
                n = ds.import_hermes_parquet(str(p), src)
                total += n
                print(f"  {src}: {n} entries")
        if ds_args.glaive:
            glaive = project_root / "dataset_glaive" / "glaive-function-calling-v2.json"
            if glaive.exists():
                n = ds.import_glaive_json(str(glaive))
                total += n
                print(f"  glaive: {n} entries")
        print(f"\nTotal new: {total}. Manifest: {len(ds.manifest)} entries")
        return 0
    if argv and argv[0] == "dataset-search":
        ds_parser = argparse.ArgumentParser(prog="delux dataset-search", description="Search the Dataset RAG for similar agent trajectories.")
        ds_parser.add_argument("query", nargs="+", help="Search query")
        ds_parser.add_argument("--home", default=None, help="DELUX_HOME workspace.")
        ds_args = ds_parser.parse_args(argv[1:])
        root = Path(ds_args.home).expanduser().resolve() if ds_args.home else default_root()
        from .dataset_rag import DatasetRAG
        ds = DatasetRAG(root)
        query = " ".join(ds_args.query)
        print(ds.search_formatted(query, top_k=5))
        return 0
    if argv and argv[0] == "dataset-package":
        pkg_parser = argparse.ArgumentParser(prog="delux dataset-package", description="Package the dataset RAG for distribution.")
        pkg_parser.add_argument("--home", default=None, help="DELUX_HOME workspace.")
        pkg_parser.add_argument("--output", default=None, help="Output path for the package.")
        pkg_args = pkg_parser.parse_args(argv[1:])
        root = Path(pkg_args.home).expanduser().resolve() if pkg_args.home else default_root()
        from .dataset_rag import DatasetRAG
        ds = DatasetRAG(root)
        count = ds.count()
        if count == 0:
            print("No dataset RAG data to package.")
            return 0
        import gzip, shutil
        dst = Path(pkg_args.output) if pkg_args.output else Path(root).parent.parent / "assets" / "dataset-rag.jsonl.gz"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if ds.entries_path.exists():
            with open(ds.entries_path, "rb") as src_f:
                with gzip.open(dst, "wb") as dst_f:
                    shutil.copyfileobj(src_f, dst_f)
            print(f"Packaged {count} entries → {dst} ({dst.stat().st_size / 1024 / 1024:.0f}MB)")
        elif ds.entries_gz.exists():
            dst.write_bytes(ds.entries_gz.read_bytes())
            print(f"Copied {count} entries → {dst} ({dst.stat().st_size / 1024 / 1024:.0f}MB)")
        else:
            print("No entries file found.")
        return 0
    if argv and argv[0] == "install-skills":
        install_parser = argparse.ArgumentParser(prog="delux install-skills", description="Install default delux-* skills to DELUX_HOME/skills/.")
        install_parser.add_argument("--home", default=None, help="DELUX_HOME workspace. Defaults to ~/.delux or env.")
        install_args = install_parser.parse_args(argv[1:])
        root = Path(install_args.home).expanduser().resolve() if install_args.home else default_root()
        from .wizard.wizard import _install_default_skills, _install_skill_template

        _install_default_skills(root)
        _install_skill_template(root)
        print(f"Default skills installed at {root}/skills/")
        return 0
    if argv and argv[0] == "ide":
        ide_parser = argparse.ArgumentParser(prog="delux ide", description="Interactive terminal IDE for Delux.")
        ide_parser.add_argument("--cwd", default=os.getcwd(), help="Working directory for shell commands.")
        ide_parser.add_argument("--home", default=None, help="DELUX_HOME workspace. Defaults to ~/.delux or env.")
        ide_parser.add_argument("--max-steps", type=int, default=12, help="Maximum autonomous action steps.")
        ide_args = ide_parser.parse_args(argv[1:])
        root = Path(ide_args.home).expanduser().resolve() if ide_args.home else None
        config = load_config(root)
        ensure_workspace(config.root)
        try:
            from .tui import DeluxTUI
            app = DeluxTUI(config=config, cwd=Path(ide_args.cwd).expanduser().resolve(), max_steps=ide_args.max_steps)
            return app.run()
        except ImportError as e:
            print(f"TUI no disponible: {e}")
            print("Instala textual: pip install textual")
            return 1
    if argv and argv[0] == "gateway":
        from .gateway import run_gateway
        gw_parser = argparse.ArgumentParser(prog="delux gateway", description="Run Delux as a Telegram bot.")
        gw_parser.add_argument("--home", default=None, help="DELUX_HOME workspace. Defaults to ~/.delux or env.")
        gw_parser.add_argument("--poll-interval", type=int, default=1, help="Poll interval (seconds)")
        gw_parser.add_argument("--once", action="store_true", help="Process one message and exit")
        gw_args = gw_parser.parse_args(argv[1:])
        return run_gateway(
            config_path=gw_args.home,
            poll_interval=gw_args.poll_interval,
            single_run=gw_args.once,
        )
    if argv and argv[0] == "cron":
        from .cron import get_scheduler
        cron_parser = argparse.ArgumentParser(prog="delux cron", description="Manage cron jobs.")
        cron_parser.add_argument("action", choices=["add", "remove", "list", "run", "logs"], help="Action")
        cron_parser.add_argument("--name", default="", help="Job name")
        cron_parser.add_argument("--expression", default="", help="Cron expression")
        cron_parser.add_argument("--command", default="", help="Shell command")
        cron_parser.add_argument("--job-id", type=int, default=0, help="Job ID")
        cron_parser.add_argument("--home", default=None, help="DELUX_HOME workspace.")
        cron_args = cron_parser.parse_args(argv[1:])
        root = Path(cron_args.home).expanduser().resolve() if cron_args.home else default_root()
        sched = get_scheduler(root)
        if cron_args.action == "add":
            result = sched.add(cron_args.name, cron_args.expression, cron_args.command)
            print(result.output)
        elif cron_args.action == "remove":
            result = sched.remove(cron_args.job_id)
            print(result.output)
        elif cron_args.action == "list":
            for j in sched.list_jobs():
                status = "ON" if j.enabled else "OFF"
                print(f"  [{j.id}] {status} {j.name}: {j.expression} -> {j.command}")
                if j.last_run:
                    print(f"       last: {j.last_run}")
        elif cron_args.action == "run":
            result = sched.run_now(cron_args.job_id)
            print(result.output)
        elif cron_args.action == "logs":
            print(sched.logs(cron_args.job_id))
        return 0
    if argv and argv[0] == "kanban":
        from .kanban import get_board
        kb_parser = argparse.ArgumentParser(prog="delux kanban", description="Manage kanban board.")
        kb_parser.add_argument("action", choices=["add", "list", "move", "show", "delete"], help="Action")
        kb_parser.add_argument("--title", default="", help="Card title")
        kb_parser.add_argument("--description", default="", help="Card description")
        kb_parser.add_argument("--status", default="todo", help="Card status")
        kb_parser.add_argument("--card-id", type=int, default=0, help="Card ID")
        kb_parser.add_argument("--home", default=None, help="DELUX_HOME workspace.")
        kb_args = kb_parser.parse_args(argv[1:])
        root = Path(kb_args.home).expanduser().resolve() if kb_args.home else default_root()
        board = get_board(root)
        if kb_args.action == "add":
            result = board.add(kb_args.title, kb_args.description)
            print(result.output)
        elif kb_args.action == "list":
            print(board.list(kb_args.status))
        elif kb_args.action == "move":
            result = board.move(kb_args.card_id, kb_args.status)
            print(result.output)
        elif kb_args.action == "show":
            print(board.show(kb_args.card_id))
        elif kb_args.action == "delete":
            result = board.delete(kb_args.card_id)
            print(result.output)
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.home).expanduser().resolve() if args.home else None
    config = load_config(root)
    ensure_workspace(config.root)

    if args.init:
        print(f"Initialized Delux workspace at {config.root}")
        return 0

    if args.context:
        skills = load_skills(config.builtin_skills_dir, config.skills_dir)
        print(f"\n{BOLD}{MAGENTA}\u25c6 MEMORY{RESET}")
        print(load_memory(config.memory_file))
        print(f"\n{BOLD}{MAGENTA}\u25c6 SKILLS{RESET}")
        for skill in skills:
            badge = f" [{YELLOW}exec:{skill.exec_lang}{RESET}]" if skill.has_exec else ""
            print(f"  {GREEN}{skill.name}{RESET}{DIM}: {skill.summary}{RESET}{badge}")
        print(f"\n{BOLD}{MAGENTA}\u25c6 DOCS{RESET}")
        print(load_docs(config.docs_dir) or f"{DIM}No docs loaded.{RESET}")
        return 0

    if args.new_skill:
        from .store import slugify, upsert_skill

        slug = slugify(args.new_skill)
        skill_dir = config.skills_dir / slug
        skill_dir.mkdir(parents=True, exist_ok=True)
        summary = args.summary or "User-created skill."
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            skill_file.write_text(
                f"# {args.new_skill}\n\n"
                f"Summary: {summary}\n\n"
                "## When To Use\n\n"
                "- \n\n"
                "## Steps\n\n"
                "1. \n\n"
                "## Verification\n\n"
                "- \n\n"
                "## Caveats\n\n"
                "- \n",
                encoding="utf-8",
            )
        upsert_skill(config.memory_file, slug, summary)
        print(f"Created skill at {skill_file}")
        return 0

    prompt = " ".join(args.prompt).strip()
    if not prompt:
        try:
            from .tui import DeluxTUI

            app = DeluxTUI(config=config, cwd=Path(args.cwd).expanduser().resolve(), max_steps=args.max_steps)
            return app.run()
        except ImportError:
            print("TUI no disponible. Instala textual: pip install textual")
            return 1

    agent = Agent(config=config, cwd=Path(args.cwd).expanduser().resolve(), event_handler=_cli_event_handler)
    answer = agent.run(prompt, max_steps=args.max_steps, verbose=False)
    print(f"\n  {GREEN}✓{RESET}  {GREEN}{answer}{RESET}")
    return 0


_MAX_OUTPUT_LINES = 12


def _truncate(text: str, max_lines: int = _MAX_OUTPUT_LINES) -> str:
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    shown = "\n".join(lines[:max_lines])
    return f"{shown}\n  {DIM}... and {len(lines) - max_lines} more lines{RESET}"


def _cli_event_handler(event: str, payload: dict) -> None:
    if event == "action_started":
        action = payload.get("action", {})
        kind = action.get("action", "unknown")
        label = _ACTION_ICONS.get(kind, kind)
        color = _ACTION_COLORS.get(kind, DIM)

        if kind == "shell":
            cmd = str(action.get("command", ""))[:200]
            print(_hl(label, color, cmd))
        elif kind in ("write_file",):
            path = str(action.get("path", ""))
            content = str(action.get("content", ""))
            lines = content.count("\n") + 1 if content else 0
            print(_hl(label, color, f"{path}  ({lines} lines)"))
        elif kind in ("edit_file", "patch_file"):
            path = str(action.get("path", ""))
            old = str(action.get("old_str", ""))
            new = str(action.get("new_str", ""))
            added = new.count("\n") - old.count("\n")
            removed = old.count("\n") - new.count("\n")
            parts = []
            if added > 0 and added != 0: parts.append(f"+{added}")
            if removed > 0: parts.append(f"-{removed}")
            diff = f"  ({', '.join(parts)})" if parts else ""
            print(_hl(label, color, f"{path}{diff}"))
        elif kind in ("read_file", "view_file"):
            print(_hl(label, color, str(action.get("path", ""))))
        elif kind == "search_files":
            print(_hl(label, color, f"'{action.get('query', '')[:100]}'"))
        elif kind == "search_web":
            print(_hl(label, color, f"'{action.get('query', '')[:100]}'"))
        elif kind == "rag_query":
            print(_hl(label, color, f"'{action.get('query', '')[:100]}'"))
        elif kind == "rag_index":
            print(_hl(label, color, str(action.get("path", ""))))
        elif kind == "create_skill":
            print(_hl(label, color, action.get("name", "")))
        elif kind == "run_skill":
            s = str(action.get("skill", ""))
            a = str(action.get("args", ""))[:80]
            print(_hl(label, color, f"{s}  {a}"))
        elif kind == "move_file":
            print(_hl(label, color, f"{action.get('src', '')} → {action.get('dst', '')}"))
        elif kind.startswith("browser_"):
            detail = ""
            if kind == "browser_navigate":
                detail = str(action.get("url", ""))[:200]
            elif kind == "browser_click":
                detail = str(action.get("selector", ""))[:100]
            elif kind == "browser_type":
                detail = f"{action.get('selector', '')} = '{action.get('text', '')[:50]}'"
            elif kind == "browser_scroll":
                detail = f"{action.get('direction', 'down')} {action.get('amount', 500)}"
            print(_hl(label, color, detail))
        elif kind.startswith("vision_"):
            print(_hl(label, color, str(action.get("image_path", ""))[:200]))
        elif kind == "delegate_task":
            print(_hl(label, color, str(action.get("task", ""))[:200]))
        elif kind.startswith("cron_"):
            detail = ""
            if kind == "cron_add":
                detail = f"{action.get('name', '')} {action.get('expression', '')}"
            elif kind in ("cron_remove", "cron_enable", "cron_run", "cron_logs"):
                detail = f"job #{action.get('job_id', '')}"
            elif kind == "cron_list":
                detail = ""
            print(_hl(label, color, detail))
        elif kind.startswith("kanban_"):
            detail = ""
            if kind == "kanban_add":
                detail = str(action.get("title", ""))[:100]
            elif kind in ("kanban_move", "kanban_show", "kanban_delete", "kanban_update"):
                detail = f"card #{action.get('card_id', '')}"
            elif kind == "kanban_list":
                detail = str(action.get("status", "") or "all")
            print(_hl(label, color, detail))
        elif kind.startswith("computer_"):
            detail = ""
            if kind == "computer_click":
                detail = f"({action.get('x', 0)}, {action.get('y', 0)}) {action.get('button', 'left')}"
            elif kind == "computer_type":
                detail = str(action.get("text", ""))[:100]
            elif kind == "computer_keypress":
                detail = str(action.get("key", ""))
            print(_hl(label, color, detail))
        elif kind == "final":
            print(f"\n  ·  {GREEN}{BOLD}{action.get('message', '')}{RESET}")
        elif kind in ("remember", "save_experience", "load_experience"):
            print(_hl(label, DIM, ""))
        else:
            print(_hl(label, DIM, ""))

    elif event == "shell_output":
        chunk = str(payload.get("chunk", ""))
        if chunk:
            for line in chunk.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                if line:
                    print(f"    {line}")

    elif event == "action_finished":
        action = payload.get("action", {})
        kind = action.get("action", "unknown")
        result = str(payload.get("result", "")).strip()
        ok = result.startswith("SUCCESS:")
        raw = result
        if ok:
            detail = result[8:]
        elif result.startswith("ERROR:"):
            detail = result[6:]
        else:
            detail = result

        if ok:
            if kind == "shell" and detail:
                out = _truncate(detail, 3)
                print(_ok(out))
            elif kind in ("write_file", "edit_file", "patch_file", "verify_file", "run_skill", "rag_index"):
                if detail:
                    print(_ok(detail[:300]))
            elif kind == "rag_query":
                if detail:
                    print(_ok(detail[:200]))
            elif kind == "final":
                pass
            elif detail:
                print(_ok(detail[:200]))
        else:
            err = _truncate(detail, 5) if detail else raw[:200]
            print(f"{_fail(err)}")


if __name__ == "__main__":
    raise SystemExit(main())
