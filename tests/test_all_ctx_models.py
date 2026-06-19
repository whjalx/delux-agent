"""Test all 4 llama.cpp models as contextualizer with remote main agent."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from delux_agent.contextualizer import Contextualizer, ContextualizerConfig, SYSTEM_PROMPT
from delux_agent.llm import chat_completion

# Main agent: remote
REMOTE_API = "http://10.0.0.16:5000/v1"
REMOTE_MODEL = "gemma4"

# 4 contextualizer models on llama.cpp
CTX_MODELS = [
    {"name": "Qwen-1.5B-Q8",  "port": 11434, "model": "DeepSeek-R1-Distill-Qwen-1.5B-Q8_0.gguf",       "timeout": 40},
    {"name": "Dolphin-Qwen-1.5B", "port": 11435, "model": "dolphin3.0-qwen2.5-1.5b-q4_k_m.gguf",       "timeout": 40},
    {"name": "Gemma-4-2B",      "port": 11436, "model": "google_gemma-4-E2B-it-Q4_K_M.gguf",            "timeout": 90},
    {"name": "Qwen-7B-Q4",      "port": 11437, "model": "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",      "timeout": 90},
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

TEST_CASES = [
    ("install nginx", "Simple: single skill", ["nginx"]),
    ("setup a docker container for a python web app with nginx reverse proxy", "Complex: 3 skills", ["docker", "python", "nginx"]),
    ("commit changes and push to remote", "Git workflow", ["git"]),
    ("open port 8080 on the firewall then start my python server", "Firewall + python", ["firewall", "python"]),
]


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def run_contextualizer_test(port: int, model: str, timeout: int) -> list[dict]:
    api = f"http://127.0.0.1:{port}/v1"
    results = []

    for prompt, desc, expected_skills in TEST_CASES:
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
                max_tokens=512,
            )

            text = response.text.strip()
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

            # Check if the contextualizer kept the right skills
            kept_right = sum(1 for s in expected_skills if s.lower() in optimized.lower())
            skill_score = f"{kept_right}/{len(expected_skills)}"

            results.append({
                "prompt": prompt[:60],
                "desc": desc,
                "original_tokens": original_tokens,
                "optimized_tokens": optimized_tokens,
                "savings_pct": savings,
                "elapsed": round(elapsed, 1),
                "changes": len(changes),
                "removed": len(removed),
                "skill_score": skill_score,
                "optimized_preview": optimized[:100],
                "ok": True,
                "full_optimized": optimized,
            })
        except Exception as e:
            elapsed = time.time() - t0
            results.append({
                "prompt": prompt[:60],
                "desc": desc,
                "original_tokens": _estimate_tokens(ctx_input),
                "optimized_tokens": _estimate_tokens(prompt),
                "savings_pct": 0,
                "elapsed": round(elapsed, 1),
                "error": str(e)[:120],
                "skill_score": "N/A",
                "ok": False,
            })

    return results


def test_main_agent_response(ctx_result: dict) -> dict:
    """Send the optimized prompt through the remote main agent to see if it works."""
    t0 = time.time()
    try:
        response = chat_completion(
            REMOTE_API,
            None,
            REMOTE_MODEL,
            [
                {"role": "system", "content": "You are Delux, a helpful AI assistant. Respond with JSON actions only."},
                {"role": "user", "content": ctx_result.get("full_optimized", ctx_result["prompt"])},
            ],
            f"{REMOTE_API}/chat/completions",
            timeout=180,
            stream=False,
        )
        elapsed = time.time() - t0
        return {"ok": True, "elapsed": round(elapsed, 1), "response_preview": response.text.strip()[:150]}
    except Exception as e:
        elapsed = time.time() - t0
        return {"ok": False, "elapsed": round(elapsed, 1), "error": str(e)[:120]}


# ==========================================
# RUN TESTS
# ==========================================

all_data = {}
for m in CTX_MODELS:
    name = m["name"]
    print(f"\n{'='*70}")
    print(f"  Contextualizer: {name}")
    print(f"  Model: {m['model']} | Port: {m['port']} | Timeout: {m['timeout']}s")
    print(f"{'='*70}")

    try:
        results = run_contextualizer_test(m["port"], m["model"], m["timeout"])
    except Exception as e:
        print(f"  ERROR: {e}")
        continue

    all_data[name] = results
    ok = [r for r in results if r.get("ok")]
    if ok:
        avg_savings = sum(r["savings_pct"] for r in ok) / len(ok)
        avg_time = sum(r["elapsed"] for r in ok) / len(ok)
        avg_changes = sum(r["changes"] for r in ok) / len(ok)
    else:
        avg_savings = avg_time = avg_changes = 0

    for r in results:
        if r.get("ok"):
            print(f"  [{r['desc']}]")
            print(f"    '{r['prompt']}'")
            print(f"    {r['original_tokens']} -> {r['optimized_tokens']} | Savings: {r['savings_pct']:.0f}% | Time: {r['elapsed']}s")
            print(f"    Changes: {r['changes']} | Removed: {r['removed']} | Skill match: {r['skill_score']}")
            print(f"    → {r['optimized_preview']}")
        else:
            print(f"  [{r['desc']}] ERROR ({r['elapsed']}s): {r.get('error', '?')}")

    print(f"\n  >> AVG: {avg_savings:.0f}% savings | {avg_time:.1f}s | {avg_changes:.1f} changes")

# Summary table
print(f"\n{'='*70}")
print(f"  SUMMARY")
print(f"{'='*70}")

name_col = 22
print(f"\n  {'Model':<{name_col}} {'Savings':>8} {'Time':>7} {'Changes':>9} {'OK':>5}")
print(f"  {'-'*65}")

stats = {}
for name, results in all_data.items():
    ok = [r for r in results if r.get("ok")]
    if ok:
        avg_s = sum(r["savings_pct"] for r in ok) / len(ok)
        avg_t = sum(r["elapsed"] for r in ok) / len(ok)
        avg_c = sum(r["changes"] for r in ok) / len(ok)
        stats[name] = {"savings": avg_s, "time": avg_t, "changes": avg_c, "ok_count": len(ok), "total": len(results)}
        print(f"  {name:<{name_col}} {avg_s:>7.0f}% {avg_t:>6.1f}s {avg_c:>9.1f} {len(ok):>4}/{len(results)}")
    else:
        stats[name] = {"savings": 0, "time": 0, "changes": 0, "ok_count": 0, "total": len(results)}
        print(f"  {name:<{name_col}} {'FAIL':>8} {'':>7} {'':>9} {0:>4}/{len(results)}")

# Find best contextualizer
best_by_savings = max((n for n, s in stats.items() if s["ok_count"] > 0),
                      key=lambda n: stats[n]["savings"], default=None)
best_by_speed = min((n for n, s in stats.items() if s["ok_count"] > 0 and s["time"] > 0),
                    key=lambda n: stats[n]["time"], default=None)
best_overall = max((n for n, s in stats.items() if s["ok_count"] > 0),
                   key=lambda n: stats[n]["savings"] / max(1, stats[n]["time"]) * 100, default=None)

print(f"\n  Best savings:  {best_by_savings or 'N/A'}")
print(f"  Fastest:       {best_by_speed or 'N/A'}")
print(f"  Best overall:  {best_overall or 'N/A'}")

# Per-task comparison
print(f"\n{'='*70}")
print(f"  PER-TASK COMPARISON")
print(f"{'='*70}")

for i, (prompt, desc, _) in enumerate(TEST_CASES):
    print(f"\n  [{desc}]")
    print(f"  Input: '{prompt}'")
    for name in all_data:
        r = all_data[name][i]
        if r.get("ok"):
            print(f"    {name:<{name_col}}: {r['original_tokens']}->{r['optimized_tokens']} ({r['savings_pct']:.0f}%) {r['elapsed']}s | {r['optimized_preview'][:70]}")
        else:
            print(f"    {name:<{name_col}}: ERROR {r.get('error', '?')[:60]}")

print(f"\n{'='*70}")
print(f"  VERDICT")
print(f"{'='*70}")

# Quality analysis per model
for name, s in stats.items():
    print(f"\n  {name}:")
    print(f"    Savings:     {'GOOD' if s['savings'] > 50 else 'OK' if s['savings'] > 20 else 'POOR'} ({s['savings']:.0f}%)")
    print(f"    Speed:       {'GOOD' if s['time'] < 10 else 'OK' if s['time'] < 30 else 'SLOW'} ({s['time']:.1f}s)")
    print(f"    Reliability: {'GOOD' if s['ok_count'] == s['total'] else 'PARTIAL'} ({s['ok_count']}/{s['total']})")
