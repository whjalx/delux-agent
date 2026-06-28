#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

DELUX_HOME = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))
RAG_DIR = DELUX_HOME / "rag"


def main():
    from delux_agent.rag import RAGEngine

    engine = RAGEngine(RAG_DIR)

    if len(sys.argv) < 2:
        print("Usage: delux-rag <command> [args...]")
        print("Commands: index, search, query, status, clear, remove")
        return 1

    cmd = sys.argv[1]

    if cmd == "status":
        print(engine.status())

    elif cmd == "clear":
        engine.clear()
        print("RAG index cleared.")

    elif cmd == "remove":
        if len(sys.argv) < 3:
            print("Usage: delux-rag remove <path>")
            return 1
        removed = engine.remove_file(sys.argv[2])
        print(f"Removed {removed} chunks.")

    elif cmd == "index":
        path = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
        chunks = engine.index_directory(path, recursive=True)
        files = sum(1 for _ in Path(path).rglob("*") if _.is_file()) if Path(path).is_dir() else 1
        print(json.dumps({
            "status": "ok",
            "chunks_added": chunks,
            "files_scanned": files,
            "total_chunks": len(engine.chunks),
            "total_files": len(engine.file_hashes),
        }))

    elif cmd == "search":
        query = " ".join(sys.argv[2:])
        if not query:
            print('Usage: delux-rag search <query>')
            return 1
        results = engine.search(query, top_k=10)
        print(json.dumps({"status": "ok", "results": results}))

    elif cmd == "query":
        query = " ".join(sys.argv[2:])
        if not query:
            print('Usage: delux-rag query <query>')
            return 1
        print(engine.query(query, top_k=10))

    else:
        print(f"Unknown command: {cmd}")
        print("Commands: index, search, query, status, clear, remove")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
