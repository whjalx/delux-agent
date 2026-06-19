"""Contextualizer test: gemma vs qwen with proper timeout for thinking."""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from delux_agent.config import Config
from delux_agent.contextualizer import Contextualizer, ContextualizerConfig, SYSTEM_PROMPT
from delux_agent.llm import chat_completion


MODELS = [
    {"name": "qwen-1.5b",  "port": 11435, "model": "dolphin3.0-qwen2.5-1.5b-q4_k_m.gguf", "timeout": 60},
    {"name": "gemma-2b",   "port": 11436, "model": "google_gemma-4-E2B-it-Q4_K_M.gguf",    "timeout": 120},
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
    ("install nginx", "Simple: single skill"),
    ("setup a docker container for a python web app with nginx reverse proxy", "Complex: 3 skills"),
    ("commit changes and push to remote", "Git workflow"),
    ("create a systemd service for my app and check the logs", "Systemd + journald"),
    ("open port 8080 on the firewall then start my python server", "Firewall + python"),
]


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def test_direct_contextualizer(port: int, model: str, timeout: int) -> list[dict]:
    """Test contextualizer directly with proper timeout."""
    api = f"http://127.0.0.1:{port}/v1"
    results = []

    for prompt, desc in TEST_PROMPTS:
        ctx_input = (
            f"USER PROMPT:\n{prompt}\n\n"
            f"MEMORY:\nUser prefers bash shell. OS is Linux.\n\n"
            f"SKILLS:\n{SKILLS}\n\n"
            f"DOCS:\n\n"
            f"PLAN:\n"
        )

        t0 = time.time()
        try:
            response = chat_completion(
                api,
                None,
                model,
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": ctx_input},
                ],
                f"{api}/chat/completions",
                timeout=timeout,
                stream=False,
            )

            text = response.text.strip()
            raw_text = text
            json_start = text.find("{")
            json_end = text.rfind("}")
            if json_start >= 0 and json_end > json_start:
                text = text[json_start:json_end + 1]

            data = json.loads(text)
            optimized = data.get("prompt", prompt)
            changes = data.get("changes", [])
            removed = data.get("removed", [])

            elapsed = time.time() - t0
            original_tokens = _estimate_tokens(ctx_input)
            optimized_tokens = _estimate_tokens(optimized)
            savings = max(0, (original_tokens - optimized_tokens) / max(1, original_tokens) * 100)

            results.append({
                "prompt": prompt[:50],
                "desc": desc,
                "original_tokens": original_tokens,
                "optimized_tokens": optimized_tokens,
                "savings_pct": savings,
                "elapsed": f"{elapsed:.1f}s",
                "changes": changes,
                "removed": removed[:2] if removed else [],
                "optimized_preview": optimized[:120],
                "ok": True,
            })
        except Exception as e:
            elapsed = time.time() - t0
            results.append({
                "prompt": prompt[:50],
                "desc": desc,
                "original_tokens": _estimate_tokens(ctx_input),
                "optimized_tokens": _estimate_tokens(prompt),
                "savings_pct": 0,
                "elapsed": f"{elapsed:.1f}s",
                "error": str(e)[:100],
                "ok": False,
            })

    return results


all_data = {}

for m in MODELS:
    name = m["name"]
    timeout = m["timeout"]
    print(f"\n{'='*70}")
    print(f"  Contextualizer: {name} ({m['model']})")
    print(f"  Port: {m['port']} | Timeout: {timeout}s")
    print(f"{'='*70}")

    try:
        results = test_direct_contextualizer(m["port"], m["model"], timeout)
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        continue

    all_data[name] = results
    ok_results = [r for r in results if r.get("ok")]
    if ok_results:
        avg_savings = sum(r["savings_pct"] for r in ok_results) / len(ok_results)
        avg_time = sum(float(r["elapsed"].replace("s", "")) for r in ok_results) / len(ok_results)
        avg_changes = sum(len(r.get("changes", [])) for r in ok_results) / len(ok_results)
    else:
        avg_savings = avg_time = avg_changes = 0

    for r in results:
        print(f"\n  [{r['desc']}]")
        print(f"    Prompt:  '{r['prompt']}'")
        if r.get("ok"):
            print(f"    Tokens:  {r['original_tokens']} -> {r['optimized_tokens']} | Savings: {r['savings_pct']:.0f}% | Time: {r['elapsed']}")
            print(f"    Changes: {len(r.get('changes', []))}")
            for c in r.get("changes", [])[:2]:
                print(f"      - {c[:90]}")
            for c in r.get("removed", [])[:2]:
                print(f"      ✗ {c[:90]}")
            print(f"    Output:  {r['optimized_preview']}")
        else:
            print(f"    ERROR: {r.get('error', '?')} | Time: {r['elapsed']}")

    print(f"\n  >> AVG: {avg_savings:.0f}% savings | {avg_time:.1f}s avg | {avg_changes:.1f} changes")

# Detailed side-by-side
print(f"\n{'='*70}")
print(f"  DETAILED COMPARISON")
print(f"{'='*70}")

for i, (prompt, desc) in enumerate(TEST_PROMPTS):
    print(f"\n  [{desc}]")
    print(f"  Input: '{prompt[:60]}'")
    for name in all_data:
        r = all_data[name][i]
        if r.get("ok"):
            print(f"    {name:<12}: {r['original_tokens']} -> {r['optimized_tokens']} ({r['savings_pct']:.0f}%) | {r['elapsed']}")
            print(f"      → {r['optimized_preview'][:80]}")
        else:
            print(f"    {name:<12}: ERROR {r.get('error', '?')[:60]}")

# Final summary
print(f"\n{'='*70}")
print(f"  FINAL SUMMARY")
print(f"{'='*70}")

stats = {}
for name in all_data:
    ok_results = [r for r in all_data[name] if r.get("ok")]
    if ok_results:
        stats[name] = {
            "savings": sum(r["savings_pct"] for r in ok_results) / len(ok_results),
            "time": sum(float(r["elapsed"].replace("s", "")) for r in ok_results) / len(ok_results),
            "changes": sum(len(r.get("changes", [])) for r in ok_results) / len(ok_results),
            "opt_tokens": sum(r["optimized_tokens"] for r in ok_results) / len(ok_results),
            "ok_count": len(ok_results),
        }

print(f"\n  {'Metric':<25} {'Qwen 1.5B':<20} {'Gemma 2B (think)':<20}")
print(f"  {'-'*65}")

q = stats.get("qwen-1.5b", {})
g = stats.get("gemma-2b", {})
print(f"  {'Successful runs':<25} {q.get('ok_count', 0):>10}            {g.get('ok_count', 0):>10}")
print(f"  {'Avg savings':<25} {q.get('savings', 0):.0f}%{'':>17} {g.get('savings', 0):.0f}%{'':>17}")
print(f"  {'Avg response time':<25} {q.get('time', 0):.1f}s{'':>16} {g.get('time', 0):.1f}s{'':>16}")
print(f"  {'Avg changes reported':<25} {q.get('changes', 0):.1f}{'':>17} {g.get('changes', 0):.1f}{'':>17}")
print(f"  {'Avg output tokens':<25} {q.get('opt_tokens', 0):.0f}{'':>16} {g.get('opt_tokens', 0):.0f}{'':>16}")

print(f"\n  {'='*70}")
print(f"  QUALITY ANALYSIS")
print(f"  {'='*70}")

for name, s in stats.items():
    print(f"\n  {name}:")
    print(f"    {'✓' if s['savings'] > 50 else '✗'} Real context reduction (>50%): {s['savings']:.0f}%")
    print(f"    {'✓' if s['time'] < 15 else '✗'} Fast response (<15s): {s['time']:.1f}s")
    print(f"    {'✓' if s['changes'] > 0.5 else '✗'} Meaningful changes (>0.5 avg): {s['changes']:.1f}")
    print(f"    {'✓' if s['opt_tokens'] < 100 else '✗'} Concise output (<100 tokens): {s['opt_tokens']:.0f}")

print(f"\n  {'='*70}")
if stats.get("gemma-2b", {}).get("ok_count", 0) == len(TEST_PROMPTS):
    q_s = stats["qwen-1.5b"]["savings"]
    g_s = stats["gemma-2b"]["savings"]
    q_t = stats["qwen-1.5b"]["time"]
    g_t = stats["gemma-2b"]["time"]
    if g_s > q_s + 10:
        print(f"  VERDICT: Gemma wins with thinking — {g_s:.0f}% vs {q_s:.0f}% savings, better quality output")
        print(f"  NOTE: Gemma is {g_t/q_t:.1f}x slower but produces deeper analysis")
    else:
        print(f"  VERDICT: Qwen wins — {q_s:.0f}% vs {g_s:.0f}% savings, {q_t:.1f}s vs {g_t:.1f}s")
elif stats.get("qwen-1.5b"):
    print(f"  VERDICT: Qwen wins by default — Gemma had timeouts")
else:
    print(f"  VERDICT: Both failed")
print(f"  {'='*70}")
