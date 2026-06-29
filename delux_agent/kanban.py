from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


STATUS_TODO = "todo"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DONE = "done"
STATUS_BLOCKED = "blocked"


@dataclass
class KanbanCard:
    id: int
    title: str
    description: str
    status: str
    assignee: str
    priority: int
    created_at: str
    updated_at: str
    tags: str


@dataclass
class KanbanResult:
    ok: bool
    output: str


class KanbanBoard:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kanban_cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    status TEXT DEFAULT 'todo',
                    assignee TEXT DEFAULT '',
                    priority INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    tags TEXT DEFAULT ''
                )
            """)
            conn.commit()

    def add(self, title: str, description: str = "", tags: str = "", priority: int = 0) -> KanbanResult:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO kanban_cards (title, description, tags, priority) VALUES (?, ?, ?, ?)",
                (title, description, tags, priority),
            )
            conn.commit()
            card_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return KanbanResult(True, f"Card #{card_id} created: {title}")

    def list(self, status: str | None = None) -> str:
        with sqlite3.connect(self.db_path) as conn:
            if status:
                rows = conn.execute(
                    "SELECT id, title, status, priority, assignee, tags FROM kanban_cards WHERE status = ? ORDER BY priority DESC, id",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, title, status, priority, assignee, tags FROM kanban_cards ORDER BY status, priority DESC, id"
                ).fetchall()
        if not rows:
            return "No cards."
        lines = []
        current_status = None
        for r in rows:
            s = r[2]
            if s != current_status:
                lines.append(f"\n## {s.upper()}")
                current_status = s
            tags = f" [{r[5]}]" if r[5] else ""
            assignee = f" @{r[4]}" if r[4] else ""
            lines.append(f"  #{r[0]}: {r[1]}{assignee}{tags} (p{r[3]})")
        return "\n".join(lines)

    def update(self, card_id: int, **kwargs: Any) -> KanbanResult:
        fields = []
        values = []
        for key, val in kwargs.items():
            if key in ("title", "description", "status", "assignee", "tags", "priority"):
                fields.append(f"{key} = ?")
                values.append(val)
        if not fields:
            return KanbanResult(False, "No fields to update")
        values.append(card_id)
        fields.append("updated_at = datetime('now')")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE kanban_cards SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            conn.commit()
        return KanbanResult(True, f"Card #{card_id} updated")

    def move(self, card_id: int, status: str) -> KanbanResult:
        return self.update(card_id, status=status)

    def delete(self, card_id: int) -> KanbanResult:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM kanban_cards WHERE id = ?", (card_id,))
            conn.commit()
        return KanbanResult(True, f"Card #{card_id} deleted")

    def show(self, card_id: int) -> str:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, title, description, status, assignee, priority, created_at, updated_at, tags FROM kanban_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
        if not row:
            return f"Card #{card_id} not found."
        return (
            f"#{row[0]}: {row[1]}\n"
            f"Status: {row[3]} | Priority: {row[5]} | Assignee: {row[4]}\n"
            f"Tags: {row[8]}\n"
            f"Created: {row[6]} | Updated: {row[7]}\n"
            f"---\n{row[2]}"
        )


_boards: dict[str, KanbanBoard] = {}


def get_board(root: Path | str) -> KanbanBoard:
    key = str(root)
    if key not in _boards:
        db = Path(str(root)) / "kanban" / "kanban.db"
        _boards[key] = KanbanBoard(str(db))
    return _boards[key]
