from __future__ import annotations

import json
import math
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Optional


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+", text.lower())


def _normalize_msg(msg) -> dict:
    if isinstance(msg, dict):
        return msg
    if isinstance(msg, tuple) and len(msg) >= 2:
        try:
            return {"from": str(msg[0]), "value": str(msg[1])}
        except Exception:
            pass
    try:
        d = dict(msg)
        if "from" in d or "value" in d:
            return d
    except Exception:
        pass
    return {"from": "unknown", "value": str(msg)}


def _format_conversation(conversations: list, max_turns: int = 0) -> str:
    lines: list[str] = []
    for i, msg in enumerate(conversations):
        if max_turns and i >= max_turns:
            remaining = len(conversations) - i
            lines.append(f"  ... ({remaining} more turns)")
            break
        msg = _normalize_msg(msg)
        role = msg.get("from", "unknown")
        value = msg.get("value", "")
        lines.append(f"[{role}]: {value}")
    return "\n\n".join(lines)


_TOOL_MAP = {
    "terminal": "shell",
    "bash": "shell",
    "execute_code": "shell",
    "write_file": "write_file",
    "read_file": "read_file",
    "patch": "edit_file",
    "search_files": "search_files",
    "session_search": "rag_query",
    "memory": "remember",
    "finish": "final",
}


def _convert_args(name: str, args: dict) -> dict:
    if name == "terminal":
        return {"command": args.get("command", ""), "timeout": 60}
    if name == "bash":
        return {"command": args.get("command", ""), "timeout": 60}
    if name == "execute_code":
        code = args.get("code", "")
        escaped = code.replace("\\", "\\\\").replace("\"", "\\\"")
        safe = escaped[:500]
        return {"command": f"python3 -c \"{safe}\"", "timeout": 30}
    if name == "write_file":
        return {"path": args.get("path", ""), "content": args.get("content", "")[:500]}
    if name == "read_file":
        return {"path": args.get("path", "")}
    if name == "patch":
        return {
            "path": args.get("path", args.get("file_path", "")),
            "old_str": args.get("old_string", args.get("old_str", "")),
            "new_str": args.get("new_string", args.get("new_str", "")),
            "replace_all": False,
        }
    if name == "search_files":
        return {"query": args.get("query", args.get("pattern", ""))}
    if name == "session_search":
        return {"query": args.get("query", ""), "top_k": 5}
    if name == "memory":
        action = args.get("action", "add")
        if action == "add":
            return {"note": args.get("content", args.get("note", ""))[:300]}
        return {}
    if name == "finish":
        return {"message": args.get("reason", args.get("message", "Task complete."))}
    return {}


def _hermes_to_delux(tc: dict) -> str:
    name = tc.get("name", "")
    args = tc.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    action_name = _TOOL_MAP.get(name, "")
    if not action_name:
        return ""
    converted = _convert_args(name, args)
    if not converted:
        return ""
    action = {"action": action_name}
    action.update(converted)
    try:
        return json.dumps(action, ensure_ascii=False)
    except Exception:
        return ""


def _extract_example_turns(conversations: list, max_turns: int = 6) -> list[str]:
    def _clean_result(raw: str) -> str:
        text = raw[:500]
        if "<tool_response>" in text:
            s = text.find("<tool_response>") + len("<tool_response>")
            e = text.find("</tool_response>")
            text = text[s:e] if e > s else text[s:]
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                if "output" in parsed:
                    return str(parsed["output"])[:200]
                if "content" in parsed:
                    c = parsed["content"]
                    if isinstance(c, dict):
                        keep = {k: v for k, v in c.items()
                                if k in ("bytes_written", "files_written", "success", "matches", "line_count")}
                        if keep:
                            return json.dumps(keep)
                    return str(c)[:200]
                if "error" in parsed and parsed["error"]:
                    return f"ERROR: {str(parsed['error'])[:100]}"
                vals = [str(v)[:80] for v in parsed.values() if isinstance(v, (str, int, float, bool)) and v]
                if vals:
                    return vals[0]
                return json.dumps(parsed)[:200]
        except Exception:
            pass
        return text.strip()[:200]

    def _extract_think(text: str) -> tuple[str, str]:
        if "<think>" in text and "</think>" in text:
            s = text.find("<think>") + len("<think>")
            e = text.find("</think>")
            return text[s:e].strip(), text[e + len("</think>"):].strip()
        return "", text

    turns: list[str] = []
    last_was_mapped = True
    pending_think = ""
    last_was_think_only = False

    for raw_msg in conversations:
        msg = _normalize_msg(raw_msg)
        role = msg.get("from", "")
        value = msg.get("value", "")

        if role == "system":
            continue

        if role == "human":
            if pending_think:
                turns.append(f"// {pending_think}")
                pending_think = ""
            last_was_mapped = True
            last_was_think_only = False
            turns.append(f"USER: \"{value[:300]}\"")

        elif role == "gpt":
            text = value
            think, text = _extract_think(text)

            tool_calls: list[dict] = []
            while "<tool_call>" in text and "</tool_call>" in text:
                ts = text.find("<tool_call>") + len("<tool_call>")
                te = text.find("</tool_call>")
                if te > ts:
                    try:
                        tc = json.loads(text[ts:te])
                        tool_calls.append(tc)
                    except Exception:
                        pass
                    text = text[te + len("</tool_call>"):].strip()
                else:
                    break

            response = text.strip()[:200] if text.strip() else ""
            mapped_tcs = [tc for tc in tool_calls if _hermes_to_delux(tc)]
            has_output = bool(response) or bool(mapped_tcs)

            if think and not has_output:
                if not last_was_think_only:
                    turns.append(f"// {think}")
                last_was_think_only = True
                last_was_mapped = False
                continue
            if not has_output:
                last_was_think_only = False
                last_was_mapped = False
                continue
            last_was_think_only = False

            if think:
                pending_think = think

            if response:
                if pending_think:
                    turns.append(f"// {pending_think}")
                    pending_think = ""
                turns.append(f"AGENT: {response}")
                last_was_mapped = True

            for tc in tool_calls:
                delux_action = _hermes_to_delux(tc)
                if delux_action:
                    if pending_think:
                        turns.append(f"// {pending_think}")
                        pending_think = ""
                    turns.append(f"AGENT: {delux_action}")
                    last_was_mapped = True
                else:
                    last_was_mapped = False

        elif role == "tool":
            if not last_was_mapped:
                continue
            if pending_think:
                turns.append(f"// {pending_think}")
                pending_think = ""
            cleaned = _clean_result(value)
            turns.append(f"RESULT: \"{cleaned}\"")

        if len(turns) >= max_turns:
            break
    return turns


def _parse_conversation_from_text(text: str) -> list[dict]:
    convs: list[dict] = []
    current_role = ""
    current_value: list[str] = []
    in_conv = False

    for line in text.split("\n"):
        stripped = line.rstrip()
        if stripped == "## Conversation":
            in_conv = True
            continue
        if not in_conv:
            continue
        if stripped.startswith("## "):
            break

        role_match = re.match(r"^\[(system|human|gpt|tool)\]:\s*(.*)", stripped)
        if role_match:
            if current_role and current_value:
                convs.append({"from": current_role, "value": "\n".join(current_value)})
            current_role = role_match.group(1)
            current_value = [role_match.group(2)] if role_match.group(2) else []
        elif current_role:
            current_value.append(stripped)

    if current_role and current_value:
        convs.append({"from": current_role, "value": "\n".join(current_value)})
    return convs


def _build_markdown_entry(task, category, subcategory, tools, conversations, entry_id):
    lines = [
        f"# Task: {task}",
        f"## Category: {category}",
        f"## Subcategory: {subcategory}",
        f"## ID: {entry_id}",
        "",
        "## Tools",
        str(tools),
        "",
        "## Conversation",
        _format_conversation(conversations, max_turns=0),
        "",
    ]
    return "\n".join(lines)


class BM25Index:
    def __init__(self):
        self.docs: list[dict] = []
        self._avgdl = 0.0
        self._N = 0
        self._df: Counter = Counter()
        self._doc_lens: list[int] = []
        self._built = False
        self.k1 = 1.5
        self.b = 0.75

    def add(self, doc: dict, text: str):
        self.docs.append({"meta": doc, "text": text})
        self._built = False

    def build(self):
        N = len(self.docs)
        total_tokens = 0
        self._doc_lens = []
        self._df = Counter()
        for d in self.docs:
            toks = _tokenize(d["text"])
            self._doc_lens.append(len(toks))
            total_tokens += len(toks)
            for t in set(toks):
                self._df[t] += 1
        self._N = N
        self._avgdl = total_tokens / N if N else 1
        self._built = True

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        if not self.docs or not query.strip():
            return []
        if not self._built:
            self.build()

        qtokens = _tokenize(query)
        if not qtokens:
            return []

        idf_cache = {}
        for t in set(qtokens):
            n = self._df.get(t, 0)
            idf_cache[t] = math.log((self._N - n + 0.5) / (n + 0.5) + 1) if n else 0

        scored: list[tuple[int, float]] = []
        for i, d in enumerate(self.docs):
            dl = self._doc_lens[i]
            tf = Counter(_tokenize(d["text"]))
            score = 0.0
            for t in qtokens:
                ft = tf.get(t, 0)
                if ft:
                    score += idf_cache[t] * (ft * (self.k1 + 1)) / (ft + self.k1 * (1 - self.b + self.b * dl / self._avgdl))
            if score > 0:
                scored.append((i, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [{"index": i, "score": round(s, 4), **self.docs[i]["meta"]}
                for i, s in scored[:top_k]]

    def clear(self):
        self.docs.clear()
        self._built = False

    def __len__(self):
        return len(self.docs)


class DatasetRAG:
    SOURCE_HERMES_KIMI = "hermes-kimi"
    SOURCE_HERMES_GLM = "hermes-glm"
    SOURCE_MULTITURN = "multiturn"
    SOURCE_GLAIVE = "glaive"

    def __init__(self, root: Path):
        self.store_dir = Path(root) / "dataset-rag"
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.entries_path = self.store_dir / "entries.jsonl"
        self.entries_gz = self.store_dir / "entries.jsonl.gz"
        self.manifest_path = self.store_dir / "manifest.json"
        self.manifest: dict[str, int] = {}
        self.index = BM25Index()
        self._offsets: dict[str, int] = {}
        self._load_manifest()
        self._ensure_cache()
        self._load_index()

    def _ensure_cache(self):
        if self.entries_path.exists():
            return
        if not self.entries_gz.exists():
            return
        import gzip, shutil
        try:
            with gzip.open(self.entries_gz, "rb") as src, \
                 open(self.entries_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
        except Exception:
            try:
                self.entries_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _load_manifest(self):
        if self.manifest_path.exists():
            try:
                self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except Exception:
                self.manifest = {}

    def _save_manifest(self):
        tmp = self.manifest_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.manifest_path)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def _append_entry(self, entry: dict):
        line = json.dumps(entry, ensure_ascii=False)
        with open(self.entries_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _build_offsets(self):
        self._offsets.clear()
        if not self.entries_path.exists():
            return
        with open(self.entries_path, "r", encoding="utf-8") as f:
            while True:
                offset = f.tell()
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    src = entry.get("source", "")
                    if src:
                        self._offsets[src] = offset
                        self.index.add({
                            "source": src,
                            "id": entry.get("id", ""),
                            "task": entry.get("task", ""),
                            "category": entry.get("category", ""),
                            "subcategory": entry.get("subcategory", ""),
                        }, entry.get("search_text", ""))
                except Exception:
                    pass

    def _load_index(self):
        if not self.entries_path.exists():
            return
        self._build_offsets()
        self.index.build()

    def _read_entry(self, source: str) -> dict | None:
        offset = self._offsets.get(source)
        if offset is None:
            return None
        try:
            with open(self.entries_path, "r", encoding="utf-8") as f:
                f.seek(offset)
                line = f.readline()
            return json.loads(line.strip())
        except Exception:
            return None

    def import_hermes_parquet(self, parquet_path: str, source: str) -> int:
        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "pandas and pyarrow are required for dataset import. "
                "Install with: pip install 'delux-agent[dataset]'"
            )
        df = pd.read_parquet(parquet_path)
        count = 0
        for _, row in df.iterrows():
            entry_id = str(row["id"])
            marker = f"{source}:{entry_id}"
            if marker in self.manifest:
                continue
            task = str(row.get("task", ""))
            category = str(row.get("category", "uncategorized"))
            subcategory = str(row.get("subcategory", ""))
            tools = str(row.get("tools", ""))
            conversations = row.get("conversations", [])
            if isinstance(conversations, str):
                try:
                    conversations = json.loads(conversations)
                except Exception:
                    conversations = []
            elif not isinstance(conversations, list):
                try:
                    conversations = list(conversations)
                except Exception:
                    continue
            src = f"{source}/{category}/{entry_id}"
            search_text = f"# Task: {task}\n## Category: {category}\n## Subcategory: {subcategory}"
            entry = {
                "source": src,
                "id": entry_id,
                "task": task,
                "category": category,
                "subcategory": subcategory,
                "tools": tools,
                "conversations": conversations,
                "search_text": search_text,
            }
            self._append_entry(entry)
            self.index.add({
                "source": src,
                "id": entry_id,
                "task": task,
                "category": category,
                "subcategory": subcategory,
            }, search_text)
            self.manifest[marker] = 1
            count += 1
            if count % 2000 == 0:
                self._save_manifest()
        self._save_manifest()
        self.index.build()
        return count

    def import_glaive_json(self, json_path: str) -> int:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        count = 0
        for i, entry in enumerate(data):
            entry_id = f"glaive-{i:06d}"
            marker = f"{self.SOURCE_GLAIVE}:{entry_id}"
            if marker in self.manifest:
                continue
            system = entry.get("system", "")
            chat = entry.get("chat", "")
            conversations = [{"from": "system", "value": system}]
            if "USER:" in chat and "ASSISTANT:" in chat:
                parts = chat.split("ASSISTANT:", 1)
                user_part = parts[0].replace("USER:", "").strip()
                assistant_part = parts[1].strip()
                conversations.append({"from": "human", "value": user_part})
                conversations.append({"from": "gpt", "value": assistant_part})
            src = f"{self.SOURCE_GLAIVE}/function-calling/{entry_id}"
            entry = {
                "source": src,
                "id": entry_id,
                "task": chat[:100],
                "category": "function-calling",
                "subcategory": "",
                "conversations": conversations,
                "search_text": chat[:500],
            }
            self._append_entry(entry)
            self.index.add({"source": src, "id": entry_id}, chat[:500])
            self.manifest[marker] = 1
            count += 1
            if count % 5000 == 0:
                self._save_manifest()
        self._save_manifest()
        self.index.build()
        return count

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        return self.index.search(query, top_k=top_k)

    def get_entry_text(self, source: str) -> Optional[str]:
        entry = self._read_entry(source)
        if entry:
            return _build_markdown_entry(
                entry.get("task", ""),
                entry.get("category", ""),
                entry.get("subcategory", ""),
                entry.get("tools", ""),
                entry.get("conversations", []),
                entry.get("id", ""),
            )
        return None

    def format_few_shot(self, results: list[dict], max_turns: int = 6) -> str:
        if not results:
            return ""
        blocks: list[str] = []
        for i, r in enumerate(results[:3]):
            src = r.get("source", "")
            entry = self._read_entry(src)
            if not entry:
                continue
            task_line = entry.get("task", "")
            cat_line = entry.get("category", "")
            convs = entry.get("conversations", [])
            example_turns = _extract_example_turns(convs, max_turns=max_turns)
            preview = "\n".join(example_turns) if example_turns else "[conversation unavailable]"
            block = (
                f"### Dataset Example {i+1}: {task_line}\n"
                f"Category: {cat_line}\n\n"
                f"{preview}\n"
            )
            blocks.append(block)
        return "\n\n".join(blocks)

    def count(self) -> int:
        return len(self.manifest)

    def search_formatted(self, query: str, top_k: int = 3) -> str:
        results = self.search(query, top_k=top_k)
        if not results:
            return f"--- Dataset RAG: no matches for '{query}' ---"
        parts = [f"--- Dataset RAG ({len(results)} matches) ---"]
        for r in results:
            parts.append(
                f"\n[{r.get('source', '?')}] (score={r.get('score', 0)})\n"
                f"Task: {r.get('task', '?')[:100]}\n"
                f"Cat: {r.get('category', '?')} / {r.get('subcategory', '?')}\n---"
            )
        return "\n".join(parts)

    def status(self) -> str:
        return (
            f"Dataset RAG\n"
            f"  Indexed: {len(self.manifest)} entries\n"
            f"  BM25 docs: {len(self.index)}\n"
            f"  Store: {self.store_dir}"
        )

    def clear(self) -> None:
        shutil.rmtree(self.store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = {}
        self._offsets.clear()
        self.index = BM25Index()
        self._save_manifest()

    def export_jsonl(self, dst: str | Path) -> int:
        """Export entries.jsonl to another location (for packaging)."""
        if not self.entries_path.exists():
            return 0
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(self.entries_path.read_bytes())
        return len(self.manifest)

    def import_jsonl(self, src: str | Path, merge: bool = True) -> int:
        """Import from a pre-built entries.jsonl file."""
        src = Path(src)
        if not src.exists():
            return 0
        count = 0
        with open(src, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                entry_id = entry.get("id", "")
                source = entry.get("source", "").split("/", 1)[0]
                marker = f"{source}:{entry_id}"
                if merge and marker in self.manifest:
                    continue
                self._append_entry(entry)
                self.index.add({
                    "source": entry.get("source", ""),
                    "id": entry_id,
                    "task": entry.get("task", ""),
                    "category": entry.get("category", ""),
                    "subcategory": entry.get("subcategory", ""),
                }, entry.get("search_text", ""))
                self.manifest[marker] = 1
                count += 1
        self._save_manifest()
        self.index.build()
        return count
