from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .rag import RAGEngine


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9_]+", text.lower())


def _compute_similarity(a_tokens: set, b_tokens: set) -> float:
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = a_tokens & b_tokens
    union = a_tokens | b_tokens
    return len(intersection) / len(union)


class ExperienceDB:
    def __init__(self, root: Path):
        self.root = Path(root) / "experiences"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "experiences.json"
        self.rag_dir = self.root / "rag"
        self.rag = RAGEngine(self.rag_dir)
        self.experiences: list[dict] = []
        self._load()

    def _load(self):
        if self.db_path.exists():
            try:
                self.experiences = json.loads(self.db_path.read_text(encoding="utf-8"))
            except Exception:
                self.experiences = []

    def _save(self):
        tmp = self.db_path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(self.experiences, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(self.db_path)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def add(
        self,
        task: str,
        solution: str,
        steps: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        verified: bool = False,
    ) -> dict:
        exp = {
            "id": f"exp-{int(time.time())}",
            "task": task.strip(),
            "solution": solution.strip(),
            "steps": steps or [],
            "tags": tags or [],
            "verified": verified,
            "success_count": 1,
            "created": datetime.now(timezone.utc).isoformat(),
            "last_used": datetime.now(timezone.utc).isoformat(),
        }
        self.experiences.append(exp)
        self._save()

        rag_text = (
            f"Task: {task}\n"
            f"Solution: {solution}\n"
            f"Steps: {'; '.join(steps) if steps else 'N/A'}\n"
            f"Tags: {', '.join(tags) if tags else 'N/A'}"
        )
        exp_path = self.root / f"{exp['id']}.md"
        exp_path.write_text(rag_text, encoding="utf-8")
        self.rag.index_file(exp_path)

        return exp

    def search(self, query: str, top_k: int = 5) -> List[dict]:
        results = self.rag.search(query, top_k=top_k)
        parsed = []
        for r in results:
            source = r["source"]
            exp_id = Path(source).stem
            exp = self._find_by_id(exp_id)
            if exp:
                parsed.append({**r, "experience": exp})
        return parsed

    def find_similar(self, task: str, top_k: int = 3) -> List[dict]:
        task_tokens = set(_tokenize(task))
        scored = []
        for exp in self.experiences:
            exp_tokens = set(_tokenize(exp["task"])) | set(_tokenize(exp["solution"]))
            score = _compute_similarity(task_tokens, exp_tokens)
            if score > 0:
                scored.append((score, exp))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s[1] for s in scored[:top_k]]

    def record_success(self, exp_id: str) -> None:
        for exp in self.experiences:
            if exp["id"] == exp_id:
                exp["success_count"] = exp.get("success_count", 1) + 1
                exp["last_used"] = datetime.now(timezone.utc).isoformat()
                self._save()
                break

    def _find_by_id(self, exp_id: str) -> Optional[dict]:
        for exp in self.experiences:
            if exp["id"] == exp_id:
                return exp
        return None

    def count(self) -> int:
        return len(self.experiences)

    def summarize(self) -> str:
        if not self.experiences:
            return "No experiences saved yet."
        lines = [f"Experience DB: {len(self.experiences)} entries"]
        for exp in self.experiences[-5:]:
            verified = "✓" if exp.get("verified") else " "
            count = exp.get("success_count", 1)
            lines.append(
                f"  [{verified}] {exp['id']} (x{count}) "
                f"{exp['task'][:80]}"
            )
        if len(self.experiences) > 5:
            lines.append(f"  ... and {len(self.experiences) - 5} more")
        return "\n".join(lines)
