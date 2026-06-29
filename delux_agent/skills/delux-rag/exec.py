#!/usr/bin/env python3
"""delux-rag: RAG-powered code indexing and search."""

import json
import os
import sys
from pathlib import Path

DELUX_HOME = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
RAG_DIR = DELUX_HOME / "rag"


def _err(msg: str) -> None:
    print(json.dumps({"status": "error", "error": msg}))


def _ok(data: dict = None) -> None:
    print(json.dumps({"status": "ok", "data": data or {}}))


def _get_engine():
    """Import and return RAGEngine, or None with error printed."""
    try:
        from delux_agent.rag import RAGEngine
    except ImportError:
        _err(
            "delux_agent.rag module not found. "
            "Install with: pip install delux-agent[rag] "
            "or ensure delux_agent is in your PYTHONPATH."
        )
        return None
    try:
        return RAGEngine(RAG_DIR)
    except Exception as e:
        _err(f"failed to initialise RAG engine: {e}")
        return None


def cmd_status(engine) -> None:
    try:
        s = engine.status()
        if isinstance(s, str):
            try:
                data = json.loads(s)
            except json.JSONDecodeError:
                data = {"status_text": s}
        else:
            data = s
        _ok(data)
    except Exception as e:
        _err(f"status failed — index may be corrupted: {e}")


def cmd_clear(engine) -> None:
    try:
        engine.clear()
        _ok({"message": "RAG index cleared"})
    except PermissionError:
        _err("permission denied: cannot clear index directory")
    except Exception as e:
        _err(f"clear failed: {e}")


def cmd_remove(engine, path_arg: str) -> None:
    if not path_arg:
        _err("usage: delux-rag remove <path>")
        return
    try:
        removed = engine.remove_file(path_arg)
        _ok({"removed_chunks": removed, "path": path_arg})
    except Exception as e:
        _err(f"remove failed for '{path_arg}': {e}")


def _walk_files(root: Path, recursive: bool):
    """Yield Path objects for valid text files, skipping binaries."""
    TEXT_EXTENSIONS = {
        ".py", ".c", ".h", ".cpp", ".hpp", ".cc", ".hh", ".cxx", ".hxx",
        ".rs", ".go", ".java", ".kt", ".kts", ".scala", ".swift",
        ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
        ".rb", ".rake", ".gemspec",
        ".php", ".phtml", ".phps",
        ".sh", ".bash", ".zsh", ".fish",
        ".pl", ".pm", ".t",
        ".lua", ".r", ".R", ".jl",
        ".html", ".htm", ".css", ".scss", ".sass", ".less",
        ".xml", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
        ".md", ".rst", ".txt", ".tex", ".log",
        ".mk", ".cmake", ".cmake.in",
        ".tf", ".tfvars", ".hcl",
        ".proto", ".graphql", ".sql",
        ".vim", ".el", ".lisp", ".clj", ".cljs", ".edn",
        ".dockerfile", ".dockerignore", ".gitignore",
    }
    if root.is_file():
        yield root
        return

    if not recursive:
        try:
            for p in root.iterdir():
                if p.is_file() and not p.name.startswith("."):
                    yield p
        except PermissionError:
            _err(f"permission denied reading directory: {root}")
        return

    try:
        for p in root.rglob("*"):
            if p.is_file() and not any(part.startswith(".") for part in p.parts):
                if p.suffix.lower() in TEXT_EXTENSIONS or p.suffix == "":
                    yield p
    except PermissionError as e:
        _err(f"permission denied during indexing: {e}")


def cmd_index(engine, path_arg: str) -> None:
    target = Path(path_arg) if path_arg else Path.cwd()
    if not target.exists():
        _err(f"path not found: {target}")
        return

    try:
        chunks = engine.index_directory(str(target), recursive=True)
    except PermissionError:
        _err(f"permission denied indexing: {target}")
        return
    except Exception as e:
        _err(f"indexing failed: {e}")
        return

    files_scanned = sum(1 for _ in _walk_files(target, True))
    total_chunks = len(engine.chunks) if hasattr(engine, "chunks") else -1
    total_files = len(engine.file_hashes) if hasattr(engine, "file_hashes") else -1

    _ok({
        "chunks_added": chunks,
        "files_scanned": files_scanned,
        "total_chunks": total_chunks,
        "total_files": total_files,
    })


def cmd_search(engine, query: str) -> None:
    if not query:
        _err("usage: delux-rag search <query>")
        return
    try:
        results = engine.search(query, top_k=10)
        _ok({"results": results, "query": query})
    except Exception as e:
        _err(f"search failed: {e}")


def cmd_query(engine, query: str) -> None:
    if not query:
        _err("usage: delux-rag query <query>")
        return
    try:
        result = engine.query(query, top_k=10)
        if isinstance(result, str):
            try:
                data = json.loads(result)
            except json.JSONDecodeError:
                data = {"answer": result}
        else:
            data = result
        _ok(data)
    except Exception as e:
        _err(f"query failed: {e}")


def main() -> int:
    if len(sys.argv) < 2:
        _err("usage: delux-rag <index|search|query|status|clear|remove> [args...]")
        return 0

    cmd = sys.argv[1]
    path_arg = sys.argv[2] if len(sys.argv) > 2 else ""

    if cmd in ("index", "search", "query", "status", "clear", "remove"):
        engine = _get_engine()
        if engine is None:
            return 0

    if cmd == "status":
        cmd_status(engine)
    elif cmd == "clear":
        cmd_clear(engine)
    elif cmd == "remove":
        cmd_remove(engine, path_arg)
    elif cmd == "index":
        cmd_index(engine, path_arg)
    elif cmd == "search":
        cmd_search(engine, " ".join(sys.argv[2:]))
    elif cmd == "query":
        cmd_query(engine, " ".join(sys.argv[2:]))
    else:
        _err(f"unknown command: {cmd}. Valid: index, search, query, status, clear, remove")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        _err("interrupted")
        sys.exit(0)
    except Exception as e:
        _err(f"unexpected error: {e}")
        sys.exit(0)
