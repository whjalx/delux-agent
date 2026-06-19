"""Contextualizer test: all 3 local models on ports 11434-6."""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from delux_agent.config import Config
from delux_agent.contextualizer import Contextualizer, ContextualizerConfig


MODELS = [
    {"name": "llama-1b",   "port": 11434, "model": "Llama-3.2-1B-Instruct-Q4_K_M.gguf"},
    {"name": "qwen-1.5b",  "port": 11435, "model": "dolphin3.0-qwen2.5-1.5b-q4_k_m.gguf"},
    {"name": "gemma-2b",   "port": 11436, "model": "google_gemma-4-E2B-it-Q4_K_M.gguf"},
]

SKILLS = """--- skill:nginx ---
Install and configure nginx web server on Linux. Supports Debian and Fedora.
Steps: install package, start service, enable on boot, verify with curl.

--- skill:docker ---
Docker container management. Build, run, stop, remove containers.
Includes docker-compose workflows.

--- skill:git ---
Git operations: clone, commit, push, pull, branch, merge, rebase.
SSH and HTTPS authentication.

--- skill:python ---
Python virtual environments, pip, venv, requirements.txt.
Install packages, run scripts, manage dependencies.

--- skill:systemd ---
Systemd service management: create unit files, enable, start, restart, check status.
Journalctl log inspection."""

TEST_PROMPTS = [
    ("install nginx", "Simple single-skill request"),
    ("setup a docker container for a python web app with nginx reverse proxy", "Multi-skill, complex"),
    ("commit changes and push to remote", "Git workflow"),
    ("create a systemd service for my app and check the logs", "Systemd + journalctl"),
]


def test_contextualizer(port: int, model: str) -> list[dict]:
    api = f"http://127.0.0.1:{port}/v1"
    cfg = ContextualizerConfig(
        enabled=True,
        model=model,
        provider="openai",
        api_base=api,
        api_endpoint=f"{api}/chat/completions",
    )
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        (tmpdir / "skills").mkdir()
        (tmpdir / "docs").mkdir()
        (tmpdir / "sessions").mkdir()
        mem = tmpdir / "memory" / "memory.md"
        mem.parent.mkdir()
        mem.write_text("")
        main_cfg = Config(
            model=model,
            provider="openai",
            api_base=api,
            api_endpoint=f"{api}/chat/completions",
            api_key=None,
            root=tmpdir,
            memory_file=mem,
            skills_dir=tmpdir / "skills",
            docs_dir=tmpdir / "docs",
            sessions_dir=tmpdir / "sessions",
            testing_dir=tmpdir / "testing",
            lang="en",
            request_timeout=60,
            shell="sh",
        )
        ctx = Contextualizer(main_cfg, cfg)

    results = []
    for prompt, desc in TEST_PROMPTS:
        t0 = time.time()
        r = ctx.contextualize(
            user_prompt=prompt,
            memory="User prefers bash shell",
            skills=SKILLS,
            docs="",
        )
        elapsed = time.time() - t0
        results.append({
            "prompt": prompt[:40],
            "desc": desc,
            "original_tokens": r.original_tokens,
            "optimized_tokens": r.optimized_tokens,
            "savings_pct": r.savings_pct,
            "elapsed": f"{elapsed:.1f}s",
            "changes": r.changes[:2],
            "optimized_preview": r.prompt[:80],
        })
    return results


for m in MODELS:
    name = m["name"]
    print(f"\n{'='*60}")
    print(f"  Contextualizer: {name} ({m['model']})")
    print(f"  Port: {m['port']}")
    print(f"{'='*60}")

    try:
        results = test_contextualizer(m["port"], m["model"])
    except Exception as e:
        print(f"  ERROR: {e}")
        continue

    total_savings = sum(r["savings_pct"] for r in results) / len(results)
    total_time = sum(float(r["elapsed"].replace("s", "")) for r in results) / len(results)

    for r in results:
        print(f"\n  [{r['desc']}]")
        print(f"    Prompt: '{r['prompt']}'")
        print(f"    Tokens: {r['original_tokens']} -> {r['optimized_tokens']} | Savings: {r['savings_pct']:.0f}% | Time: {r['elapsed']}")
        print(f"    Optimized: {r['optimized_preview']}")

    print(f"\n  >> AVG: {total_savings:.0f}% savings | {total_time:.1f}s avg response")

print(f"\n{'='*60}")
print(f"  SUMMARY")
print(f"{'='*60}")
print(f"\n  {'Model':<20} {'Avg Savings':<15} {'Avg Time':<15}")
print(f"  {'-'*50}")

for m in MODELS:
    name = m["name"]
    try:
        results = test_contextualizer(m["port"], m["model"])
        total_savings = sum(r["savings_pct"] for r in results) / len(results)
        total_time = sum(float(r["elapsed"].replace("s", "")) for r in results) / len(results)
        print(f"  {name:<20} {total_savings:.0f}%{'':>12} {total_time:.1f}s{'':>12}")
    except Exception:
        print(f"  {name:<20} {'ERROR':<15} {'ERROR':<15}")
