from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable


@dataclass
class CronJob:
    id: int
    name: str
    expression: str
    command: str
    enabled: bool
    last_run: str | None
    next_run: str | None
    created_at: str


@dataclass
class CronResult:
    ok: bool
    output: str


class CronScheduler:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._running = False
        self._thread: threading.Thread | None = None
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cron_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    expression TEXT NOT NULL,
                    command TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    last_run TEXT,
                    next_run TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cron_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    started_at TEXT,
                    finished_at TEXT,
                    exit_code INTEGER,
                    output TEXT,
                    FOREIGN KEY (job_id) REFERENCES cron_jobs(id)
                )
            """)
            conn.commit()

    def add(self, name: str, expression: str, command: str) -> CronResult:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO cron_jobs (name, expression, command) VALUES (?, ?, ?)",
                    (name, expression, command),
                )
                conn.commit()
            return CronResult(True, f"Cron job '{name}' created: {expression} -> {command}")
        except sqlite3.IntegrityError:
            return CronResult(False, f"Cron job '{name}' already exists")

    def remove(self, job_id: int) -> CronResult:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
            conn.commit()
        return CronResult(True, f"Removed job {job_id}")

    def list_jobs(self) -> list[CronJob]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, name, expression, command, enabled, last_run, next_run, created_at FROM cron_jobs ORDER BY id"
            ).fetchall()
        return [
            CronJob(
                id=r[0], name=r[1], expression=r[2], command=r[3],
                enabled=bool(r[4]), last_run=r[5], next_run=r[6], created_at=r[7],
            )
            for r in rows
        ]

    def enable(self, job_id: int, enabled: bool) -> CronResult:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE cron_jobs SET enabled = ? WHERE id = ?", (1 if enabled else 0, job_id))
            conn.commit()
        return CronResult(True, f"Job {job_id} {'enabled' if enabled else 'disabled'}")

    def run_now(self, job_id: int, timeout: int = 60) -> CronResult:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT command FROM cron_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return CronResult(False, f"Job {job_id} not found")
        command = row[0]
        started = datetime.now().isoformat()
        try:
            proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
            output = (proc.stdout + proc.stderr).strip()[:5000]
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            output = f"Timed out after {timeout}s"
            exit_code = -1
        except Exception as e:
            output = str(e)
            exit_code = -2
        finished = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE cron_jobs SET last_run = ? WHERE id = ?",
                (started, job_id),
            )
            conn.execute(
                "INSERT INTO cron_logs (job_id, started_at, finished_at, exit_code, output) VALUES (?, ?, ?, ?, ?)",
                (job_id, started, finished, exit_code, output[:5000]),
            )
            conn.commit()
        return CronResult(exit_code == 0, output)

    def logs(self, job_id: int, limit: int = 10) -> str:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT started_at, finished_at, exit_code, substr(output, 1, 200) FROM cron_logs WHERE job_id = ? ORDER BY id DESC LIMIT ?",
                (job_id, limit),
            ).fetchall()
        if not rows:
            return "No logs for this job."
        lines = [f"Last {len(rows)} runs for job {job_id}:"]
        for r in rows:
            lines.append(f"  [{r[0]}] exit={r[1]} output={r[2]}")
        return "\n".join(lines)


_scheduler: CronScheduler | None = None


def get_scheduler(root: Path | str) -> CronScheduler:
    global _scheduler
    if _scheduler is None:
        db = Path(str(root)) / "cron" / "cron.db"
        _scheduler = CronScheduler(str(db))
    return _scheduler
