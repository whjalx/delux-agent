#!/usr/bin/env python3
"""Dataset RAG manager — production-grade CLI with JSON output."""

import json
import os
import sys
import traceback
from pathlib import Path

MAX_QUERY_SIZE = 2000
MAX_TOP_K = 50
MIN_TOP_K = 1
DEFAULT_TOP_K_SEARCH = 5
DEFAULT_TOP_K_FEWSHOT = 3
MAX_FEWSHOT_TURNS = 20
MIN_FEWSHOT_TURNS = 1

VALID_COMMANDS = {"import", "search", "few-shot", "status", "clear", "export"}


def _get_delux_home() -> Path:
    """Get DELUX_HOME directory. Returns Path."""
    raw = os.environ.get("DELUX_HOME", str(Path.home() / ".delux"))
    try:
        path = Path(raw).expanduser().resolve()
    except Exception:
        path = Path.home() / ".delux"
    return path


def _get_project_root() -> Path:
    """Get project root directory."""
    return Path(__file__).resolve().parent.parent.parent


def _validate_query(query: str) -> str:
    """Validate and sanitize a query string."""
    if not query or not isinstance(query, str):
        raise ValueError("Query is required and must be a non-empty string")
    query = query.strip()
    if not query:
        raise ValueError("Query is required and must be a non-empty string")
    if len(query) > MAX_QUERY_SIZE:
        raise ValueError(f"Query too long ({len(query)} chars, max {MAX_QUERY_SIZE})")
    return query


def _validate_top_k(raw: str | int | None, default: int) -> int:
    """Validate top_k parameter."""
    if raw is None:
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid top_k value: '{raw}'. Must be an integer.")
    if val < MIN_TOP_K or val > MAX_TOP_K:
        raise ValueError(f"top_k must be between {MIN_TOP_K} and {MAX_TOP_K}, got {val}")
    return val


def _validate_max_turns(raw: str | int | None) -> int:
    """Validate max_turns parameter."""
    if raw is None:
        return DEFAULT_FEWSHOT_TURNS * 2
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid max_turns value: '{raw}'. Must be an integer.")
    if val < MIN_FEWSHOT_TURNS or val > MAX_FEWSHOT_TURNS:
        raise ValueError(f"max_turns must be between {MIN_FEWSHOT_TURNS} and {MAX_FEWSHOT_TURNS}, got {val}")
    return val


def _import_dataset_rag() -> tuple:
    """Import DatasetRAG class. Returns (DatasetRAG, None) or (None, error_dict)."""
    try:
        from delux_agent.dataset_rag import DatasetRAG
        return DatasetRAG, None
    except ImportError as e:
        return None, {
            "status": "error",
            "error": (
                f"delux_agent.dataset_rag module cannot be imported: {str(e)[:300]}. "
                "Install delux-agent with dataset support: pip install 'delux-agent[dataset]'"
            ),
        }
    except Exception as e:
        return None, {
            "status": "error",
            "error": f"Unexpected error importing DatasetRAG: {str(e)[:500]}",
        }


def _instantiate_rag(delux_home: Path) -> tuple:
    """Instantiate DatasetRAG. Returns (DatasetRAG, None) or (None, error_dict)."""
    DatasetRAG, import_err = _import_dataset_rag()
    if import_err is not None:
        return None, import_err
    try:
        ds = DatasetRAG(delux_home)
        return ds, None
    except FileNotFoundError as e:
        return None, {
            "status": "error",
            "error": f"Cannot create DatasetRAG store at {delux_home / 'dataset-rag'}: {str(e)[:300]}",
        }
    except PermissionError as e:
        return None, {
            "status": "error",
            "error": f"Permission denied creating DatasetRAG store: {str(e)[:300]}",
        }
    except OSError as e:
        return None, {
            "status": "error",
            "error": f"Filesystem error creating DatasetRAG store: {str(e)[:300]}",
        }
    except Exception as e:
        return None, {
            "status": "error",
            "error": f"Failed to initialize DatasetRAG: {str(e)[:500]}",
        }


def cmd_status(delux_home: Path) -> str:
    """Execute the 'status' command. Returns JSON string."""
    ds, err = _instantiate_rag(delux_home)
    if err is not None:
        return json.dumps(err, indent=2, ensure_ascii=False)

    try:
        entry_count = len(ds.manifest)
        index_size = len(ds.index)
        store_dir = str(ds.store_dir)
        manifest_path = str(ds.manifest_path)
        entries_path = str(ds.entries_path)
        entries_exists = ds.entries_path.exists()
        entries_size = ds.entries_path.stat().st_size if entries_exists else 0

        return json.dumps({
            "status": "ok",
            "data": {
                "indexed_entries": entry_count,
                "bm25_docs": index_size,
                "store_directory": store_dir,
                "manifest_path": manifest_path,
                "entries_path": entries_path,
                "entries_file_exists": entries_exists,
                "entries_file_size_bytes": entries_size,
                "entries_file_size_mb": round(entries_size / (1024 * 1024), 2) if entries_exists else 0,
            },
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"Failed to get status: {str(e)[:500]}",
        }, indent=2, ensure_ascii=False)


def cmd_clear(delux_home: Path) -> str:
    """Execute the 'clear' command. Returns JSON string."""
    ds, err = _instantiate_rag(delux_home)
    if err is not None:
        return json.dumps(err, indent=2, ensure_ascii=False)

    try:
        ds.clear()
        return json.dumps({
            "status": "ok",
            "data": {
                "message": "Dataset RAG store cleared.",
                "store_directory": str(ds.store_dir),
            },
        }, indent=2, ensure_ascii=False)
    except PermissionError as e:
        return json.dumps({
            "status": "error",
            "error": f"Permission denied clearing DatasetRAG store: {str(e)[:300]}",
        }, indent=2, ensure_ascii=False)
    except OSError as e:
        return json.dumps({
            "status": "error",
            "error": f"Filesystem error clearing DatasetRAG store: {str(e)[:300]}",
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"Failed to clear DatasetRAG: {str(e)[:500]}",
        }, indent=2, ensure_ascii=False)


def cmd_import(delux_home: Path, extra_args: list[str]) -> str:
    """Execute the 'import' command. Returns JSON string."""
    ds, err = _instantiate_rag(delux_home)
    if err is not None:
        return json.dumps(err, indent=2, ensure_ascii=False)

    project_root = _get_project_root()
    results: list[dict] = []
    total_imported = 0
    errors: list[str] = []

    parquet_sources = [
        {
            "name": "Hermes Kimi",
            "path": project_root / "dataset_hermes" / "data" / "kimi" / "train.parquet",
            "source": ds.SOURCE_HERMES_KIMI,
        },
        {
            "name": "Hermes GLM",
            "path": project_root / "dataset_hermes" / "data" / "glm-5.1" / "train.parquet",
            "source": ds.SOURCE_HERMES_GLM,
        },
        {
            "name": "Multiturn",
            "path": project_root / "dataset_multiturn" / "data" / "train-00000-of-00001.parquet",
            "source": ds.SOURCE_MULTITURN,
        },
    ]

    for src_info in parquet_sources:
        if not src_info["path"].exists():
            results.append({
                "source": src_info["name"],
                "status": "skipped",
                "reason": f"File not found: {src_info['path']}",
            })
            continue

        try:
            n = ds.import_hermes_parquet(str(src_info["path"]), src_info["source"])
            total_imported += n
            results.append({
                "source": src_info["name"],
                "status": "ok",
                "imported": n,
            })
        except ImportError as e:
            errors.append(f"{src_info['name']}: {str(e)[:200]}")
            results.append({
                "source": src_info["name"],
                "status": "error",
                "error": str(e)[:300],
            })
        except PermissionError as e:
            errors.append(f"{src_info['name']}: Permission denied - {str(e)[:200]}")
            results.append({
                "source": src_info["name"],
                "status": "error",
                "error": f"Permission denied: {str(e)[:200]}",
            })
        except OSError as e:
            errors.append(f"{src_info['name']}: I/O error - {str(e)[:200]}")
            results.append({
                "source": src_info["name"],
                "status": "error",
                "error": f"I/O error: {str(e)[:200]}",
            })
        except Exception as e:
            errors.append(f"{src_info['name']}: Unexpected error - {str(e)[:200]}")
            results.append({
                "source": src_info["name"],
                "status": "error",
                "error": str(e)[:300],
            })

    if "--glaive" in extra_args:
        glaive_path = project_root / "dataset_glaive" / "glaive-function-calling-v2.json"
        if not glaive_path.exists():
            results.append({
                "source": "Glaive",
                "status": "skipped",
                "reason": f"File not found: {glaive_path}",
            })
        else:
            try:
                n = ds.import_glaive_json(str(glaive_path))
                total_imported += n
                results.append({
                    "source": "Glaive",
                    "status": "ok",
                    "imported": n,
                })
            except json.JSONDecodeError as e:
                errors.append(f"Glaive: Invalid JSON - {str(e)[:200]}")
                results.append({
                    "source": "Glaive",
                    "status": "error",
                    "error": f"Invalid JSON: {str(e)[:200]}",
                })
            except PermissionError as e:
                errors.append(f"Glaive: Permission denied - {str(e)[:200]}")
                results.append({
                    "source": "Glaive",
                    "status": "error",
                    "error": f"Permission denied: {str(e)[:200]}",
                })
            except OSError as e:
                errors.append(f"Glaive: I/O error - {str(e)[:200]}")
                results.append({
                    "source": "Glaive",
                    "status": "error",
                    "error": f"I/O error: {str(e)[:200]}",
                })
            except Exception as e:
                errors.append(f"Glaive: Unexpected error - {str(e)[:200]}")
                results.append({
                    "source": "Glaive",
                    "status": "error",
                    "error": str(e)[:300],
                })

    try:
        manifest_count = len(ds.manifest)
    except Exception:
        manifest_count = 0

    return json.dumps({
        "status": "ok",
        "data": {
            "total_imported": total_imported,
            "manifest_entries": manifest_count,
            "results": results,
            "errors": errors,
            "error_count": len(errors),
        },
    }, indent=2, ensure_ascii=False)


def cmd_search(delux_home: Path, query: str, top_k: int = DEFAULT_TOP_K_SEARCH) -> str:
    """Execute the 'search' command. Returns JSON string."""
    try:
        query = _validate_query(query)
    except ValueError as e:
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

    try:
        top_k = _validate_top_k(top_k, DEFAULT_TOP_K_SEARCH)
    except ValueError as e:
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

    ds, err = _instantiate_rag(delux_home)
    if err is not None:
        return json.dumps(err, indent=2, ensure_ascii=False)

    try:
        results = ds.search(query, top_k=top_k)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"Search failed: {str(e)[:500]}",
        }, indent=2, ensure_ascii=False)

    if not results:
        return json.dumps({
            "status": "ok",
            "data": {
                "query": query,
                "matches": 0,
                "results": [],
                "message": f"No matches found for: {query}",
            },
        }, indent=2, ensure_ascii=False)

    formatted_results = []
    for r in results:
        formatted_results.append({
            "source": r.get("source", "?"),
            "score": r.get("score", 0),
            "task": r.get("task", "")[:200],
            "category": r.get("category", "?"),
            "subcategory": r.get("subcategory", ""),
        })

    return json.dumps({
        "status": "ok",
        "data": {
            "query": query,
            "matches": len(results),
            "top_k": top_k,
            "results": formatted_results,
        },
    }, indent=2, ensure_ascii=False, default=str)


def cmd_few_shot(delux_home: Path, query: str, top_k: int = DEFAULT_TOP_K_FEWSHOT, max_turns: int = 6) -> str:
    """Execute the 'few-shot' command. Returns JSON string."""
    try:
        query = _validate_query(query)
    except ValueError as e:
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

    try:
        top_k = _validate_top_k(top_k, DEFAULT_TOP_K_FEWSHOT)
    except ValueError as e:
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

    try:
        max_turns = _validate_max_turns(max_turns)
    except ValueError as e:
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

    ds, err = _instantiate_rag(delux_home)
    if err is not None:
        return json.dumps(err, indent=2, ensure_ascii=False)

    try:
        results = ds.search(query, top_k=top_k)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"Search failed for few-shot: {str(e)[:500]}",
        }, indent=2, ensure_ascii=False)

    if not results:
        return json.dumps({
            "status": "ok",
            "data": {
                "query": query,
                "examples": 0,
                "formatted": "",
                "message": f"No dataset examples found for: {query}",
            },
        }, indent=2, ensure_ascii=False)

    try:
        formatted = ds.format_few_shot(results, max_turns=max_turns)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"Failed to format few-shot examples: {str(e)[:500]}",
        }, indent=2, ensure_ascii=False)

    example_metadata = []
    for r in results:
        example_metadata.append({
            "source": r.get("source", "?"),
            "score": r.get("score", 0),
            "task": r.get("task", "")[:200],
            "category": r.get("category", "?"),
        })

    return json.dumps({
        "status": "ok",
        "data": {
            "query": query,
            "examples": len(results),
            "example_metadata": example_metadata,
            "formatted": formatted,
        },
    }, indent=2, ensure_ascii=False)


def cmd_export(delux_home: Path, dst_path: str | None = None) -> str:
    """Execute the 'export' command. Returns JSON string."""
    ds, err = _instantiate_rag(delux_home)
    if err is not None:
        return json.dumps(err, indent=2, ensure_ascii=False)

    if not dst_path:
        dst_path = str(delux_home / "dataset-rag" / "export.jsonl")

    try:
        dst = Path(dst_path).expanduser().resolve()
    except Exception:
        dst = Path(dst_path)

    try:
        count = ds.export_jsonl(dst)
        return json.dumps({
            "status": "ok",
            "data": {
                "exported_entries": count,
                "destination": str(dst),
            },
        }, indent=2, ensure_ascii=False)
    except PermissionError as e:
        return json.dumps({
            "status": "error",
            "error": f"Permission denied writing export to {dst}: {str(e)[:300]}",
        }, indent=2, ensure_ascii=False)
    except OSError as e:
        return json.dumps({
            "status": "error",
            "error": f"Filesystem error during export: {str(e)[:300]}",
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"Export failed: {str(e)[:500]}",
        }, indent=2, ensure_ascii=False)


def dataset_rag_main(argv: list[str]) -> str:
    """Main entry point. Returns JSON string."""
    if not argv:
        return json.dumps({
            "status": "error",
            "error": (
                "No command provided. "
                f"Usage: delux-dataset-rag <command> [args...]\n"
                f"Commands: {', '.join(sorted(VALID_COMMANDS))}"
            ),
        }, indent=2, ensure_ascii=False)

    cmd = argv[0].strip().lower()
    args = argv[1:]

    delux_home = _get_delux_home()

    try:
        if cmd == "status":
            return cmd_status(delux_home)

        elif cmd == "clear":
            return cmd_clear(delux_home)

        elif cmd == "import":
            return cmd_import(delux_home, args)

        elif cmd == "search":
            top_k = DEFAULT_TOP_K_SEARCH
            query_parts: list[str] = []
            i = 0
            while i < len(args):
                if args[i] == "--top-k" and i + 1 < len(args):
                    top_k = args[i + 1]
                    i += 2
                elif args[i].startswith("--top-k="):
                    top_k = args[i].split("=", 1)[1]
                    i += 1
                else:
                    query_parts.append(args[i])
                    i += 1
            query = " ".join(query_parts)
            try:
                top_k_int = _validate_top_k(top_k, DEFAULT_TOP_K_SEARCH)
            except ValueError as e:
                return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)
            if not query:
                return json.dumps({
                    "status": "error",
                    "error": "Query is required. Usage: delux-dataset-rag search [--top-k N] <query>",
                }, ensure_ascii=False)
            return cmd_search(delux_home, query, top_k=top_k_int)

        elif cmd == "few-shot":
            top_k = DEFAULT_TOP_K_FEWSHOT
            max_turns = 6
            query_parts: list[str] = []
            i = 0
            while i < len(args):
                if args[i] == "--top-k" and i + 1 < len(args):
                    top_k = args[i + 1]
                    i += 2
                elif args[i].startswith("--top-k="):
                    top_k = args[i].split("=", 1)[1]
                    i += 1
                elif args[i] == "--max-turns" and i + 1 < len(args):
                    max_turns = args[i + 1]
                    i += 2
                elif args[i].startswith("--max-turns="):
                    max_turns = args[i].split("=", 1)[1]
                    i += 1
                else:
                    query_parts.append(args[i])
                    i += 1
            query = " ".join(query_parts)
            try:
                top_k_int = _validate_top_k(top_k, DEFAULT_TOP_K_FEWSHOT)
            except ValueError as e:
                return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)
            try:
                max_turns_int = _validate_max_turns(max_turns)
            except ValueError as e:
                return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)
            if not query:
                return json.dumps({
                    "status": "error",
                    "error": "Query is required. Usage: delux-dataset-rag few-shot [--top-k N] [--max-turns N] <query>",
                }, ensure_ascii=False)
            return cmd_few_shot(delux_home, query, top_k=top_k_int, max_turns=max_turns_int)

        elif cmd == "export":
            dst = args[0] if args else None
            return cmd_export(delux_home, dst)

        else:
            return json.dumps({
                "status": "error",
                "error": (
                    f"Unknown command: '{cmd}'. "
                    f"Valid commands: {', '.join(sorted(VALID_COMMANDS))}"
                ),
            }, indent=2, ensure_ascii=False)

    except KeyboardInterrupt:
        return json.dumps({
            "status": "error",
            "error": "Interrupted by user (Ctrl+C)",
        }, indent=2, ensure_ascii=False)
    except Exception:
        return json.dumps({
            "status": "error",
            "error": f"Unhandled error in command '{cmd}': {traceback.format_exc()[:1000]}",
        }, indent=2, ensure_ascii=False)


def _print_json(status: str, data: dict | None = None, error: str | None = None) -> None:
    """Print a standardized JSON response."""
    if status == "error":
        print(json.dumps({"status": "error", "error": error or "Unknown error"}, ensure_ascii=False))
    else:
        print(json.dumps({"status": "ok", "data": data or {}}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        output = dataset_rag_main(sys.argv[1:])
        print(output)
    except KeyboardInterrupt:
        _print_json("error", error="Interrupted by user (Ctrl+C)")
        sys.exit(130)
    except Exception:
        _print_json("error", error=f"Unhandled CLI error: {traceback.format_exc()[:1000]}")
        sys.exit(1)
