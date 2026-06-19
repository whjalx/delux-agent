"""Contextualizer test: gemma vs qwen. Gemma has thinking enabled."""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from delux_agent.config import Config
from delux_agent.contextualizer import Contextualizer, ContextualizerConfig


MODELS = [
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
Journalctl log inspection.

--- skill:firewall ---
Firewall configuration: ufw, firewalld, iptables.
Open ports, allow services, block IPs."""

TEST_PROMPTS = [
    ("install nginx", "Simple: single skill, common task"),
    ("setup a docker container for a python web app with nginx reverse proxy", "Complex: 3 skills combined"),
    ("commit changes and push to remote", "Git: basic workflow"),
    ("create a systemd service for my app and check the logs", "Systemd + journald"),
    ("open port 8080 on the firewall then start my python server", "Firewall + python app"),
]


def test_contextualizer(port: int, model: str, timeout: int = 90) -> list[dict]:
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
        (tmpdir / "testing").mkdir()
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
            request_timeout=timeout,
            shell="sh",
        )
        ctx = Contextualizer(main_cfg, cfg)

    results = []
    for prompt, desc in TEST_PROMPTS:
        t0 = time.time()
        r = ctx.contextualize(
            user_prompt=prompt,
            memory="User prefers bash shell. OS is Linux.",
            skills=SKILLS,
            docs="",
        )
        elapsed = time.time() - t0
        results.append({
            "prompt": prompt[:50],
            "desc": desc,
            "original_tokens": r.original_tokens,
            "optimized_tokens": r.optimized_tokens,
            "savings_pct": r.savings_pct,
            "elapsed": f"{elapsed:.1f}s",
            "changes": r.changes,
            "optimized_preview": r.prompt[:120],
            "changes_count": len(r.changes) if r.changes else 0,
        })
    return results


all_data = {}

for m in MODELS:
    name = m["name"]
    timeout = 90 if "gemma" in name else 60
    print(f"\n{'='*70}")
    print(f"  Contextualizer: {name} ({m['model']})")
    print(f"  Port: {m['port']} | Timeout: {timeout}s")
    print(f"{'='*70}")

    try:
        results = test_contextualizer(m["port"], m["model"], timeout)
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        continue

    all_data[name] = results
    avg_savings = sum(r["savings_pct"] for r in results) / len(results)
    avg_time = sum(float(r["elapsed"].replace("s", "")) for r in results) / len(results)
    avg_changes = sum(r["changes_count"] for r in results) / len(results)

    for r in results:
        print(f"\n  [{r['desc']}]")
        print(f"    Prompt:  '{r['prompt']}'")
        print(f"    Tokens:  {r['original_tokens']} -> {r['optimized_tokens']} | Savings: {r['savings_pct']:.0f}% | Time: {r['elapsed']}")
        print(f"    Changes: {r['changes_count']}")
        if r["changes"]:
            for c in r["changes"]:
                print(f"      - {c[:90]}")
        print(f"    Output:  {r['optimized_preview']}")

    print(f"\n  >> AVG: {avg_savings:.0f}% savings | {avg_time:.1f}s avg | {avg_changes:.1f} changes")

# Side-by-side summary
print(f"\n{'='*70}")
print(f"  DETAILED COMPARISON")
print(f"{'='*70}")

for i, (prompt, desc) in enumerate(TEST_PROMPTS):
    print(f"\n  [{desc}]")
    print(f"  Input: '{prompt[:60]}'")
    for name in all_data:
        r = all_data[name][i]
        print(f"    {name:<12}: {r['original_tokens']} -> {r['optimized_tokens']} tokens ({r['savings_pct']:.0f}% saved) | {r['elapsed']}")
        print(f"      → {r['optimized_preview'][:80]}")

# Final summary
print(f"\n{'='*70}")
print(f"  FINAL SUMMARY")
print(f"{'='*70}")
print(f"\n  {'Metric':<25} {'Qwen 1.5B':<20} {'Gemma 2B':<20}")
print(f"  {'-'*65}")

stats = {}
for name in all_data:
    results = all_data[name]
    avg_savings = sum(r["savings_pct"] for r in results) / len(results)
    avg_time = sum(float(r["elapsed"].replace("s", "")) for r in results) / len(results)
    avg_changes = sum(r["changes_count"] for r in results) / len(results)
    avg_opt_tokens = sum(r["optimized_tokens"] for r in results) / len(results)
    stats[name] = {
        "savings": avg_savings,
        "time": avg_time,
        "changes": avg_changes,
        "opt_tokens": avg_opt_tokens,
    }

q = stats["qwen-1.5b"]
g = stats["gemma-2b"]
print(f"  {'Avg savings':<25} {q['savings']:.0f}%{'':>14} {g['savings']:.0f}%{'':>14}")
print(f"  {'Avg response time':<25} {q['time']:.1f}s{'':>15} {g['time']:.1f}s{'':>15}")
print(f"  {'Avg changes reported':<25} {q['changes']:.1f}{'':>17} {g['changes']:.1f}{'':>17}")
print(f"  {'Avg output tokens':<25} {q['opt_tokens']:.0f}{'':>16} {g['opt_tokens']:.0f}{'':>16}")

# Verdict
print(f"\n  {'='*70}")
if g["savings"] > q["savings"] and g["time"] < 20:
    print(f"  VERDICT: Gemma 2B wins — better savings ({g['savings']:.0f}% vs {q['savings']:.0f}%), thinking produces quality")
elif q["savings"] > g["savings"]:
    print(f"  VERDICT: Qwen 1.5B wins — better real savings ({q['savings']:.0f}% vs {g['savings']:.0f}%), faster ({q['time']:.1f}s vs {g['time']:.1f}s)")
else:
    print(f"  VERDICT: Close — Gemma {g['savings']:.0f}% / Qwen {q['savings']:.0f}%, choose based on speed vs quality")
print(f"  {'='*70}")
