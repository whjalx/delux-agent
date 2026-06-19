from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List

CHUNK_SIZE = 600
CHUNK_OVERLAP = 80
MAX_FILE_SIZE = 10 * 1024 * 1024
TEXT_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".txt", ".json",
    ".yml", ".yaml", ".toml", ".cfg", ".ini", ".conf",
    ".sh", ".bash", ".zsh", ".fish", ".rb", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".java", ".kt", ".swift",
    ".css", ".scss", ".less", ".html", ".xml", ".sql",
    ".vue", ".svelte", ".php", ".lua",
    ".env", ".gitignore", ".editorconfig",
    ".csv", ".log", ".rst",
}


@dataclass
class Chunk:
    text: str
    source: str
    chunk_id: int
    start_line: int
    end_line: int


@dataclass
class IndexData:
    chunks: List[Chunk] = field(default_factory=list)
    file_hashes: dict = field(default_factory=dict)
    chunk_size: int = CHUNK_SIZE


def _file_hash(path: Path) -> str:
    try:
        data = path.read_bytes()
        return str(hash(data) & 0xFFFFFFFF)
    except OSError:
        return ""


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9_]+", text.lower())


def _is_binary(path: Path) -> bool:
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        return False
    if ext in {".gif", ".jpg", ".jpeg", ".png", ".svg", ".ico", ".woff", ".woff2",
               ".ttf", ".eot", ".mp3", ".mp4", ".avi", ".mov", ".pdf",
               ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
               ".o", ".so", ".dll", ".exe", ".dylib", ".bin", ".dat"}:
        return True
    try:
        with open(path, "rb") as fh:
            head = fh.read(8192)
        return b"\x00" in head
    except OSError:
        return True


class RAGEngine:
    def __init__(self, persist_dir: str | Path):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.persist_dir / "rag_index.json"
        self.chunks: List[Chunk] = []
        self.file_hashes: dict[str, str] = {}
        self._load()
        self._bm25_cache = None

    def _chunk_text(self, text: str, source: str) -> List[Chunk]:
        lines = text.split("\n")
        chunks: List[Chunk] = []
        buf: List[str] = []
        buf_len = 0
        cid = 0
        start = 1

        for i, line in enumerate(lines, 1):
            if buf_len + len(line) > CHUNK_SIZE and buf:
                chunks.append(Chunk(
                    text="\n".join(buf),
                    source=source,
                    chunk_id=cid,
                    start_line=start,
                    end_line=i - 1,
                ))
                overlap = []
                olen = 0
                for ol in reversed(buf):
                    if olen + len(ol) >= CHUNK_OVERLAP:
                        break
                    overlap.insert(0, ol)
                    olen += len(ol)
                buf = overlap
                buf_len = olen
                start = max(1, i - len(overlap))
                cid += 1
            buf.append(line)
            buf_len += len(line)

        if buf:
            chunks.append(Chunk(
                text="\n".join(buf),
                source=source,
                chunk_id=cid,
                start_line=start,
                end_line=len(lines),
            ))
        return chunks

    def index_file(self, path: str | Path) -> int:
        path = Path(path)
        if not path.is_file():
            return 0
        if path.stat().st_size > MAX_FILE_SIZE:
            return 0
        if _is_binary(path):
            return 0
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return 0

        rel = str(path)
        h = _file_hash(path)
        if self.file_hashes.get(rel) == h:
            return 0

        self.chunks = [c for c in self.chunks if c.source != rel]
        new_chunks = self._chunk_text(text, rel)
        self.chunks.extend(new_chunks)
        self.file_hashes[rel] = h
        self._bm25_cache = None
        self._save()
        return len(new_chunks)

    def index_text(self, text: str, source: str) -> int:
        rel = str(source)
        if rel in self.file_hashes:
            self.chunks = [c for c in self.chunks if c.source != rel]
        new_chunks = self._chunk_text(text, rel)
        self.chunks.extend(new_chunks)
        self.file_hashes[rel] = hex(hash(text) & 0xFFFFFF)
        self._bm25_cache = None
        return len(new_chunks)

    def index_directory(self, path: str | Path, recursive: bool = True) -> int:
        path = Path(path)
        if not path.exists():
            return 0
        if path.is_file():
            return self.index_file(path)

        pattern = "**/*" if recursive else "*"
        total = 0
        for f in sorted(path.glob(pattern)):
            if f.is_file():
                total += self.index_file(f)
        return total

    def remove_file(self, path: str | Path) -> int:
        rel = str(Path(path))
        old = len(self.chunks)
        self.chunks = [c for c in self.chunks if c.source != rel]
        self.file_hashes.pop(rel, None)
        removed = old - len(self.chunks)
        if removed:
            self._bm25_cache = None
            self._save()
        return removed

    def clear(self) -> None:
        self.chunks.clear()
        self.file_hashes.clear()
        self._bm25_cache = None
        self._save()

    def _ensure_bm25(self):
        if self._bm25_cache is not None:
            return
        N = len(self.chunks)
        if N == 0:
            self._bm25_cache = ({}, 0, 0, 0, 0, 0)
            return

        total_tokens = 0
        doc_lens: List[int] = []
        df: Counter = Counter()
        for c in self.chunks:
            toks = _tokenize(c.text)
            doc_lens.append(len(toks))
            total_tokens += len(toks)
            for t in set(toks):
                df[t] += 1

        avgdl = total_tokens / N if N else 1
        self._bm25_cache = (df, avgdl, N, doc_lens)

    def search(self, query: str, top_k: int = 5):
        if not self.chunks or not query.strip():
            return []
        self._ensure_bm25()
        df, avgdl, N, doc_lens = self._bm25_cache

        qtokens = _tokenize(query)
        if not qtokens:
            return []

        k1 = 1.5
        b = 0.75
        idf_cache = {}
        for t in set(qtokens):
            n = df.get(t, 0)
            idf_cache[t] = math.log((N - n + 0.5) / (n + 0.5) + 1) if n else 0

        scored: List[tuple[int, float]] = []
        for i, c in enumerate(self.chunks):
            dl = doc_lens[i]
            ctoks = _tokenize(c.text)
            tf = Counter(ctoks)
            score = 0.0
            for t in qtokens:
                ft = tf.get(t, 0)
                if ft:
                    score += idf_cache[t] * (ft * (k1 + 1)) / (ft + k1 * (1 - b + b * dl / avgdl))
            if score > 0:
                scored.append((i, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        results = []
        for i, score in scored[:top_k]:
            c = self.chunks[i]
            results.append({
                "text": c.text,
                "source": c.source,
                "chunk_id": c.chunk_id,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "score": round(score, 4),
            })
        return results

    def query(self, query: str, top_k: int = 5) -> str:
        results = self.search(query, top_k=top_k)
        if not results:
            return f"--- RAG: no results for '{query}' ---"

        parts = [f"--- RAG Results ({len(results)} matches) ---"]
        for r in results:
            src = r["source"]
            lines = f"L{r['start_line']}-L{r['end_line']}"
            score = r["score"]
            text = r["text"][:600]
            parts.append(f"\n[{src}:{lines}] (score={score})\n{text}\n---")
        parts.append(f"({len(self.chunks)} chunks, {len(self.file_hashes)} files)")
        return "\n".join(parts)

    def status(self) -> str:
        return (
            f"RAG Engine – BM25 (pure Python)\n"
            f"  Chunks: {len(self.chunks)}\n"
            f"  Files:  {len(self.file_hashes)}\n"
            f"  Store:  {self.index_path}"
        )

    def _save(self):
        data = {
            "chunks": [
                {"text": c.text, "source": c.source,
                 "chunk_id": c.chunk_id,
                 "start_line": c.start_line, "end_line": c.end_line}
                for c in self.chunks
            ],
            "file_hashes": self.file_hashes,
            "chunk_size": CHUNK_SIZE,
        }
        tmp = self.index_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.index_path)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def _load(self):
        if not self.index_path.exists():
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            self.chunks = [Chunk(**c) for c in data.get("chunks", [])]
            self.file_hashes = data.get("file_hashes", {})
        except Exception:
            self.chunks = []
            self.file_hashes = {}
