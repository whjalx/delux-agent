"""
delux_agent/indexer.py
======================
Codebase Indexer — graphify-style knowledge graph with Obsidian vault export.

Responsibilities:
  1. Scan the current working directory and map every source file.
  2. Extract symbols (classes, functions, exports) per file.
  3. Detect import/dependency relationships between files.
  4. Cache the index to ~/.delux/project_index.json (mtime-based invalidation).
  5. Export the index as Obsidian-compatible Markdown notes (wikilinks + YAML front-matter).
  6. Resolve [[wikilink]] tokens typed in the IDE prompt → file content snippets.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator


# ── Constants ──────────────────────────────────────────────────────────────────

INDEX_FILE = "project_index.json"
OBSIDIAN_DIR = "obsidian"

# Extensions we index and their canonical language label
LANG_MAP: dict[str, str] = {
    ".py":   "python",
    ".js":   "javascript",
    ".ts":   "typescript",
    ".jsx":  "javascript",
    ".tsx":  "typescript",
    ".go":   "go",
    ".rs":   "rust",
    ".rb":   "ruby",
    ".c":    "c",
    ".cpp":  "cpp",
    ".h":    "c",
    ".hpp":  "cpp",
    ".java": "java",
    ".sh":   "bash",
    ".fish": "fish",
    ".md":   "markdown",
    ".toml": "toml",
    ".json": "json",
    ".yaml": "yaml",
    ".yml":  "yaml",
}

# Directories to always skip
SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules",
    ".mypy_cache", "dist", "build", ".ruff_cache", ".eggs", "*.egg-info",
    ".tox", ".cache", ".idea", ".vscode",
}

# Max characters read from each file for symbol extraction
READ_LIMIT = 16_000

# Max characters injected per [[wikilink]] expansion in the prompt
WIKILINK_INJECT_LIMIT = 8_000


# ── Data Classes ───────────────────────────────────────────────────────────────

@dataclass
class FileEntry:
    rel_path: str          # relative to project root, e.g. "delux_agent/agent.py"
    language: str          # "python", "markdown", etc.
    size: int              # bytes
    mtime: float           # Unix timestamp
    symbols: list[str] = field(default_factory=list)    # class/function names
    imports: list[str] = field(default_factory=list)    # rel_path references
    summary: str = ""      # one-line description (first docstring / heading)

    def obsidian_name(self) -> str:
        """Safe Obsidian note name (no slashes)."""
        return self.rel_path.replace("/", " › ")


@dataclass
class ProjectIndex:
    project: str
    cwd: str
    generated_at: str
    files: dict[str, FileEntry] = field(default_factory=dict)  # rel_path → entry

    # ── Derived helpers ───────────────────────────────────────────────────────

    def reverse_deps(self) -> dict[str, list[str]]:
        """Map rel_path → list of rel_paths that import it."""
        rev: dict[str, list[str]] = {k: [] for k in self.files}
        for rel, entry in self.files.items():
            for imp in entry.imports:
                if imp in rev:
                    rev[imp].append(rel)
        return rev

    def search(self, query: str) -> list[FileEntry]:
        """Fuzzy search over file paths and symbols."""
        q = query.lower()
        results: list[FileEntry] = []
        for entry in self.files.values():
            if q in entry.rel_path.lower() or any(q in s.lower() for s in entry.symbols):
                results.append(entry)
        return sorted(results, key=lambda e: (q not in e.rel_path.lower(), e.rel_path))

    def resolve_wikilink(
        self,
        link: str,
        embedding_store: EmbeddingStore | None = None,
        config = None,
    ) -> tuple[FileEntry | None, float]:
        """Find the best matching FileEntry for a [[wikilink]] token. Returns (entry, similarity_score)."""
        link_clean = link.strip().lower()
        # 1. Exact rel_path match
        for rel, entry in self.files.items():
            if rel.lower() == link_clean:
                return entry, 1.0
        # 2. Basename match
        for rel, entry in self.files.items():
            if Path(rel).name.lower() == link_clean:
                return entry, 1.0
        # 3. Partial match (startswith or endswith)
        candidates: list[FileEntry] = []
        for rel, entry in self.files.items():
            if link_clean in rel.lower():
                candidates.append(entry)
        if len(candidates) == 1:
            return candidates[0], 1.0
        if len(candidates) > 1:
            # Prefer shortest path (most specific match)
            return sorted(candidates, key=lambda e: len(e.rel_path))[0], 1.0

        # 4. Semantic Fallback
        if embedding_store and config and embedding_store.embeddings:
            sem_results = embedding_store.search(link, config)
            if sem_results:
                best_rel, score = sem_results[0]
                if score >= 0.65: # High confidence threshold
                    entry = self.files.get(best_rel)
                    if entry:
                        return entry, score

        return None, 0.0


# ── Symbol Extractors ──────────────────────────────────────────────────────────

def _extract_python(text: str) -> tuple[list[str], list[str], str]:
    """Return (symbols, imports, summary) for Python source."""
    symbols: list[str] = []
    imports: list[str] = []

    # Symbols: class and def at module level (no leading whitespace or 4-space indent)
    for m in re.finditer(r"^(?:class|def)\s+(\w+)", text, re.MULTILINE):
        symbols.append(m.group(1))

    # Imports: from .module import ... / import module
    for m in re.finditer(r"^from\s+\.([a-zA-Z_][a-zA-Z0-9_]*)\s+import", text, re.MULTILINE):
        imports.append(m.group(1))
    for m in re.finditer(r"^import\s+([a-zA-Z_][a-zA-Z0-9_.]+)", text, re.MULTILINE):
        imports.append(m.group(1).split(".")[0])

    # Summary: module docstring
    summary = ""
    doc_m = re.search(r'^"""(.*?)"""', text, re.DOTALL)
    if doc_m:
        summary = doc_m.group(1).strip().split("\n")[0][:120]

    return symbols[:40], list(dict.fromkeys(imports)), summary


def _extract_js_ts(text: str) -> tuple[list[str], list[str], str]:
    """Return (symbols, imports, summary) for JS/TS source."""
    symbols: list[str] = []
    imports: list[str] = []

    # Named exports and function/class declarations
    for m in re.finditer(r"(?:export\s+)?(?:class|function|const|let|var)\s+(\w+)", text):
        symbols.append(m.group(1))

    # Import statements: import ... from './path'
    for m in re.finditer(r"""from\s+['"]([^'"]+)['"]""", text):
        imports.append(m.group(1))

    # JSDoc summary
    summary = ""
    doc_m = re.search(r"/\*\*(.*?)\*/", text, re.DOTALL)
    if doc_m:
        lines = [l.strip().lstrip("* ") for l in doc_m.group(1).splitlines()]
        summary = " ".join(l for l in lines if l)[:120]

    return symbols[:40], list(dict.fromkeys(imports)), summary


def _extract_markdown(text: str) -> tuple[list[str], list[str], str]:
    """Return (headings, wikilinks, first-heading) for Markdown."""
    headings = re.findall(r"^#{1,3}\s+(.+)", text, re.MULTILINE)
    links = re.findall(r"\[\[([^\]]+)\]\]", text)
    summary = headings[0] if headings else ""
    return headings[:20], links[:30], summary


def _extract_symbols(path: Path, language: str, text: str) -> tuple[list[str], list[str], str]:
    if language == "python":
        return _extract_python(text)
    if language in ("javascript", "typescript"):
        return _extract_js_ts(text)
    if language == "markdown":
        return _extract_markdown(text)
    return [], [], ""


# ── Import Path Resolution ────────────────────────────────────────────────────

def _resolve_import(raw_import: str, current_file: str, all_rel_paths: set[str]) -> str | None:
    """
    Try to resolve a raw import string to an actual rel_path in the project.
    Handles:
      - Relative Python module names (e.g. "llm" → "delux_agent/llm.py")
      - JS paths (e.g. "./store" → "src/store.ts")
    """
    current_dir = str(Path(current_file).parent)

    # Normalize JS/TS relative paths
    if raw_import.startswith("./") or raw_import.startswith("../"):
        base = raw_import.lstrip("./").lstrip("../")
        for ext in (".ts", ".tsx", ".js", ".jsx", ".py"):
            candidate = f"{current_dir}/{base}{ext}".lstrip("/")
            if candidate in all_rel_paths:
                return candidate
        return None

    # Python: try same-package sibling
    for ext in (".py",):
        candidate = f"{current_dir}/{raw_import}{ext}".lstrip("/")
        if candidate in all_rel_paths:
            return candidate

    return None


# ── File Scanner ───────────────────────────────────────────────────────────────

def _should_skip(path: Path) -> bool:
    for part in path.parts:
        if part in SKIP_DIRS or part.endswith(".egg-info"):
            return True
    return False


def _iter_source_files(root: Path) -> Iterator[Path]:
    """Yield all indexable source files under root."""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if _should_skip(path.relative_to(root)):
            continue
        if path.suffix in LANG_MAP:
            yield path


# ── Core Builder ───────────────────────────────────────────────────────────────

def build_index(cwd: Path, force: bool = False, delux_root: Path | None = None) -> ProjectIndex:
    """
    Scan `cwd` and build a ProjectIndex.
    Uses mtime-based cache stored at `delux_root / INDEX_FILE`.
    """
    cache_path: Path | None = (delux_root / INDEX_FILE) if delux_root else None

    # ── Try loading existing cache ────────────────────────────────────────────
    if not force and cache_path and cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if data.get("cwd") == str(cwd):
                cached = _deserialize_index(data)
                if _is_cache_valid(cwd, cached):
                    return cached
        except Exception:
            pass

    # ── Fresh scan ────────────────────────────────────────────────────────────
    project_name = cwd.name
    entries: dict[str, FileEntry] = {}

    source_files = list(_iter_source_files(cwd))
    all_rel_paths: set[str] = set()
    for path in source_files:
        rel = str(path.relative_to(cwd))
        all_rel_paths.add(rel)

    for path in source_files:
        rel = str(path.relative_to(cwd))
        lang = LANG_MAP.get(path.suffix, "text")
        stat = path.stat()

        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:READ_LIMIT]
        except OSError:
            text = ""

        symbols, raw_imports, summary = _extract_symbols(path, lang, text)

        # Resolve imports to actual rel_paths in the project
        resolved_imports: list[str] = []
        for raw in raw_imports:
            resolved = _resolve_import(raw, rel, all_rel_paths)
            if resolved:
                resolved_imports.append(resolved)

        entries[rel] = FileEntry(
            rel_path=rel,
            language=lang,
            size=stat.st_size,
            mtime=stat.st_mtime,
            symbols=symbols,
            imports=resolved_imports,
            summary=summary,
        )

    index = ProjectIndex(
        project=project_name,
        cwd=str(cwd),
        generated_at=datetime.now().isoformat(timespec="seconds"),
        files=entries,
    )

    # ── Save cache ────────────────────────────────────────────────────────────
    if cache_path:
        try:
            cache_path.write_text(
                json.dumps(_serialize_index(index), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    return index


def _is_cache_valid(cwd: Path, cached: "ProjectIndex") -> bool:
    """Return True if every cached mtime still matches the filesystem."""
    for rel, entry in cached.files.items():
        path = cwd / rel
        if not path.exists():
            return False
        if abs(path.stat().st_mtime - entry.mtime) > 1:
            return False
    return True


# ── Serialization ─────────────────────────────────────────────────────────────

def _serialize_index(index: ProjectIndex) -> dict:
    return {
        "project": index.project,
        "cwd": index.cwd,
        "generated_at": index.generated_at,
        "files": {
            rel: {
                "language": e.language,
                "size": e.size,
                "mtime": e.mtime,
                "symbols": e.symbols,
                "imports": e.imports,
                "summary": e.summary,
            }
            for rel, e in index.files.items()
        },
    }


def _deserialize_index(data: dict) -> ProjectIndex:
    files: dict[str, FileEntry] = {}
    for rel, d in data.get("files", {}).items():
        files[rel] = FileEntry(
            rel_path=rel,
            language=d.get("language", "text"),
            size=int(d.get("size", 0)),
            mtime=float(d.get("mtime", 0)),
            symbols=d.get("symbols", []),
            imports=d.get("imports", []),
            summary=d.get("summary", ""),
        )
    return ProjectIndex(
        project=data.get("project", ""),
        cwd=data.get("cwd", ""),
        generated_at=data.get("generated_at", ""),
        files=files,
    )


# ── Obsidian Vault Export ──────────────────────────────────────────────────────

def export_obsidian_vault(index: ProjectIndex, vault_dir: Path) -> int:
    """
    Generate one Obsidian note per file + a root _index.md MOC.
    Returns number of notes written.
    """
    vault_dir.mkdir(parents=True, exist_ok=True)
    rev = index.reverse_deps()
    count = 0

    for rel, entry in sorted(index.files.items()):
        note_content = _build_obsidian_note(entry, rev.get(rel, []))
        note_path = vault_dir / f"{entry.obsidian_name()}.md"
        note_path.write_text(note_content, encoding="utf-8")
        count += 1

    # Write MOC (Map of Content) root note
    moc = _build_moc(index)
    (vault_dir / "_index.md").write_text(moc, encoding="utf-8")
    count += 1

    return count


def _build_obsidian_note(entry: FileEntry, referenced_by: list[str]) -> str:
    lines: list[str] = []

    # YAML front-matter
    lines += [
        "---",
        f"language: {entry.language}",
        f"size_bytes: {entry.size}",
        f"tags: [delux-index, {entry.language}]",
        "---",
        "",
        f"# {Path(entry.rel_path).name}",
        "",
    ]

    # Path breadcrumb
    parts = Path(entry.rel_path).parts
    if len(parts) > 1:
        lines.append(f"`{'  /  '.join(parts)}`")
        lines.append("")

    # Summary
    if entry.summary:
        lines += [f"> {entry.summary}", ""]

    # Symbols
    if entry.symbols:
        lines.append("## Símbolos")
        for sym in entry.symbols:
            lines.append(f"- `{sym}`")
        lines.append("")

    # Imports (wikilinks)
    if entry.imports:
        lines.append("## Importa")
        for imp in entry.imports:
            note_name = FileEntry(
                rel_path=imp, language="", size=0, mtime=0
            ).obsidian_name()
            lines.append(f"- [[{note_name}]]")
        lines.append("")

    # Referenced by
    if referenced_by:
        lines.append("## Referenciado por")
        for ref in sorted(referenced_by):
            note_name = FileEntry(
                rel_path=ref, language="", size=0, mtime=0
            ).obsidian_name()
            lines.append(f"- [[{note_name}]]")
        lines.append("")

    return "\n".join(lines)


def _build_moc(index: ProjectIndex) -> str:
    lines: list[str] = [
        "---",
        "tags: [delux-index, moc]",
        "---",
        "",
        f"# {index.project} — Knowledge Graph",
        "",
        f"> Generated by Delux Agent on {index.generated_at}",
        f"> `{index.cwd}`",
        "",
        "## Archivos",
        "",
    ]

    # Group by directory
    by_dir: dict[str, list[FileEntry]] = {}
    for entry in sorted(index.files.values(), key=lambda e: e.rel_path):
        d = str(Path(entry.rel_path).parent)
        by_dir.setdefault(d, []).append(entry)

    for d, entries in sorted(by_dir.items()):
        dir_label = d if d != "." else "(raíz)"
        lines.append(f"### `{dir_label}`")
        for entry in entries:
            note_name = entry.obsidian_name()
            sym_preview = ", ".join(f"`{s}`" for s in entry.symbols[:3])
            if sym_preview:
                sym_preview = f" — {sym_preview}"
            lines.append(f"- [[{note_name}]]{sym_preview}")
        lines.append("")

    return "\n".join(lines)


# ── Wikilink Expansion (for IDE prompt injection) ──────────────────────────────

def expand_wikilinks(
    prompt: str,
    index: ProjectIndex | None,
    cwd: Path,
    embedding_store: EmbeddingStore | None = None,
    config = None,
    on_semantic_match = None,
) -> tuple[str, list[str]]:
    """
    Replace [[filename]] tokens in `prompt` with file content snippets.

    Returns:
        (expanded_prompt, list_of_expanded_links)
    """
    pattern = re.compile(r"\[\[([^\]]+)\]\]")
    expanded: list[str] = []

    def _replace(m: re.Match) -> str:
        link = m.group(1).strip()

        # Try via index first
        entry: FileEntry | None = None
        score = 1.0
        if index:
            entry, score = index.resolve_wikilink(link, embedding_store, config)

        # Fallback: direct filesystem search from cwd
        resolved_path: Path | None = None
        if entry:
            resolved_path = cwd / entry.rel_path
        else:
            resolved_path = _fuzzy_find(link, cwd)

        if resolved_path is None or not resolved_path.exists():
            return m.group(0)  # leave unchanged if not found

        try:
            content = resolved_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return m.group(0)

        rel = str(resolved_path.relative_to(cwd)) if cwd in resolved_path.parents else str(resolved_path)
        lang = LANG_MAP.get(resolved_path.suffix, "")

        # Truncate if needed
        truncated = ""
        if len(content) > WIKILINK_INJECT_LIMIT:
            content = content[:WIKILINK_INJECT_LIMIT]
            truncated = f"\n... [truncado a {WIKILINK_INJECT_LIMIT} caracteres]"

        # Notify via callback if a semantic match was made
        if score < 1.0 and on_semantic_match:
            on_semantic_match(link, rel, score)

        fence = f"```{lang}" if lang else "```"
        block = (
            f"\n[Contenido de `{rel}`]:\n"
            f"{fence}\n"
            f"{content}"
            f"{truncated}\n"
            "```\n"
        )
        expanded.append(rel)
        return block

    expanded_prompt = pattern.sub(_replace, prompt)
    return expanded_prompt, expanded


def _fuzzy_find(link: str, cwd: Path) -> Path | None:
    """Filesystem fuzzy search: exact name, then suffix-stripped name."""
    link_lower = link.lower()
    # Exact relative path
    exact = cwd / link
    if exact.exists():
        return exact
    # Walk and match by filename (case-insensitive)
    for path in cwd.rglob("*"):
        if _should_skip(path.relative_to(cwd)):
            continue
        if path.is_file() and path.name.lower() == link_lower:
            return path
        if path.is_file() and path.stem.lower() == link_lower:
            return path
    return None


# ── Pretty Printers ────────────────────────────────────────────────────────────

def format_index_summary(index: ProjectIndex) -> str:
    total = len(index.files)
    by_lang: dict[str, int] = {}
    for e in index.files.values():
        by_lang[e.language] = by_lang.get(e.language, 0) + 1

    lang_lines = "  ".join(
        f"{lang}:{count}" for lang, count in sorted(by_lang.items(), key=lambda x: -x[1])
    )
    return (
        f"Project: {index.project}  |  {total} files  |  {lang_lines}\n"
        f"CWD: {index.cwd}\n"
        f"Generated: {index.generated_at}"
    )


# ── Embedding Utilities & Storage ──────────────────────────────────────────────

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Calcula la similitud de coseno entre dos vectores."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(x * y for x, y in zip(v1, v2))
    norm_v1 = sum(x * x for x in v1) ** 0.5
    norm_v2 = sum(x * x for x in v2) ** 0.5
    if norm_v1 == 0.0 or norm_v2 == 0.0:
        return 0.0
    return dot_product / (norm_v1 * norm_v2)


def make_embedding_document(entry: FileEntry, cwd: Path) -> str:
    """Genera un documento de texto compacto que describe el archivo para su embedding."""
    parts = [
        f"File: {entry.rel_path}",
        f"Language: {entry.language}",
    ]
    if entry.summary:
        parts.append(f"Summary: {entry.summary}")
    if entry.symbols:
        parts.append(f"Symbols: {', '.join(entry.symbols)}")

    # Intentar leer una previsualización del contenido del archivo
    try:
        path = cwd / entry.rel_path
        if path.exists() and path.is_file():
            content = path.read_text(encoding="utf-8", errors="replace")[:1500]
            parts.append(f"Content Preview:\n{content}")
    except Exception:
        pass

    return "\n\n".join(parts)


@dataclass
class EmbeddingStore:
    project: str
    cwd: str
    embedding_model: str
    embeddings: dict[str, list[float]] = field(default_factory=dict)
    mtimes: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, delux_root: Path, project: str) -> EmbeddingStore:
        path = delux_root / "project_embeddings.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("project") == project:
                    return cls(
                        project=project,
                        cwd=data.get("cwd", ""),
                        embedding_model=data.get("embedding_model", ""),
                        embeddings=data.get("embeddings", {}),
                        mtimes=data.get("mtimes", {}),
                    )
            except Exception:
                pass
        return cls(project=project, cwd="", embedding_model="")

    def save(self, delux_root: Path) -> None:
        path = delux_root / "project_embeddings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "project": self.project,
            "cwd": self.cwd,
            "embedding_model": self.embedding_model,
            "embeddings": self.embeddings,
            "mtimes": self.mtimes,
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def build(self, index: ProjectIndex, config, force: bool = False, on_progress=None) -> int:
        """
        Genera embeddings de forma incremental para los archivos que han cambiado o son nuevos.
        Retorna la cantidad de archivos para los cuales se generó un embedding.
        """
        from delux_agent.llm import get_embedding

        self.cwd = index.cwd
        self.project = index.project
        model = config.embedding_model
        if not model:
            return 0

        # Si el modelo configurado cambió, vaciar la caché
        if self.embedding_model != model:
            self.embeddings.clear()
            self.mtimes.clear()
            self.embedding_model = model

        to_embed = []
        for rel, entry in index.files.items():
            cached_mtime = self.mtimes.get(rel)
            if force or cached_mtime is None or abs(cached_mtime - entry.mtime) > 1 or rel not in self.embeddings:
                to_embed.append((rel, entry))

        if not to_embed:
            return 0

        api_base = config.embedding_api_base or config.api_base
        api_endpoint = config.embedding_api_endpoint or config.api_endpoint
        api_key = config.embedding_api_key or config.api_key

        count = 0
        total = len(to_embed)
        for rel, entry in to_embed:
            doc = make_embedding_document(entry, Path(index.cwd))
            try:
                vector = get_embedding(
                    api_base=api_base,
                    api_key=api_key,
                    model=model,
                    text=doc,
                    api_endpoint=api_endpoint,
                )
                self.embeddings[rel] = vector
                self.mtimes[rel] = entry.mtime
                count += 1
                if on_progress:
                    on_progress(count, total, rel)
            except Exception as exc:
                raise RuntimeError(f"Error embedding {rel}: {exc}") from exc

        # Limpiar archivos borrados
        for rel in list(self.embeddings.keys()):
            if rel not in index.files:
                self.embeddings.pop(rel, None)
                self.mtimes.pop(rel, None)

        return count

    def search(self, query: str, config) -> list[tuple[str, float]]:
        """Busca archivos mediante similitud semántica con el query."""
        from delux_agent.llm import get_embedding
        if not self.embeddings or not self.embedding_model:
            return []

        api_base = config.embedding_api_base or config.api_base
        api_endpoint = config.embedding_api_endpoint or config.api_endpoint
        api_key = config.embedding_api_key or config.api_key

        try:
            query_vector = get_embedding(
                api_base=api_base,
                api_key=api_key,
                model=self.embedding_model,
                text=query,
                api_endpoint=api_endpoint,
            )
        except Exception:
            return []

        results = []
        for rel, vector in self.embeddings.items():
            score = cosine_similarity(query_vector, vector)
            results.append((rel, score))

        return sorted(results, key=lambda x: -x[1])
