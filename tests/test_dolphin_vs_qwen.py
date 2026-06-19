"""Focused test: Dolphin (11435) vs Qwen-1.5B-Q8 (11434) as contextualizer."""
import json, time, urllib.request

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
Open ports, allow services, block IPs.

--- skill:npm ---
Node.js package management. Install, update, remove npm packages.
Initialize projects, manage package.json, run npm scripts.

--- skill:ssh ---
SSH key management, remote server connections, ssh config.
SCP file transfers, SSH tunneling, port forwarding."""

SYSTEM_PROMPT = """You are a Prompt Contextualizer for an AI agent called Delux. Your job is to optimize the context that will be sent to the main model, reducing token usage while keeping all essential information.

You will receive:
1. The user's prompt
2. Available context (memory, skills, docs)
3. The current plan (if any)

Your task:
1. Select ONLY the skills that are relevant to the user's prompt
2. Include only relevant memory entries
3. Keep docs that might help with the task
4. Add any missing context that would help (OS type, available tools, etc.)
5. Remove everything else

Respond with JSON in this exact format:
{"prompt": "optimized prompt combining user request with selected context", "changes": ["list of changes made"], "removed": ["list of things removed and why"]}

Rules:
- Keep the optimized prompt concise but complete
- Preserve all information needed to execute the task
- The optimized prompt should be self-contained
- Do not change the user's intent
- If nothing needs to be changed, return the original with empty changes"""

MODELS = [
    ("Qwen-1.5B-Q8",  11434, "DeepSeek-R1-Distill-Qwen-1.5B-Q8_0.gguf", 45),
    ("Dolphin-Qwen",  11435, "dolphin3.0-qwen2.5-1.5b-q4_k_m.gguf",     45),
]

TASKS = [
    ("install nginx", "Simple 1 skill", ["nginx"], ["docker", "git", "python", "systemd", "firewall", "npm", "ssh"]),
    ("setup a docker container for a python web app with nginx reverse proxy", "Complex 3 skills", ["docker", "python", "nginx"], ["git", "systemd", "firewall", "npm", "ssh"]),
    ("commit changes and push to remote", "Git only", ["git"], ["nginx", "docker", "python", "systemd", "firewall", "npm", "ssh"]),
    ("open port 8080 on the firewall then start my python server", "Multi: firewall+python", ["firewall", "python"], ["nginx", "docker", "git", "systemd", "npm", "ssh"]),
    ("clone the repo, install npm deps, and run tests", "Multi: git+npm", ["git", "npm"], ["nginx", "docker", "python", "systemd", "firewall", "ssh"]),
    ("create a systemd service and check logs", "Multi: systemd", ["systemd"], ["nginx", "docker", "git", "python", "firewall", "npm", "ssh"]),
    ("ssh into the server, pull latest code, and restart the service", "Complex: ssh+git+systemd", ["ssh", "git", "systemd"], ["nginx", "docker", "python", "firewall", "npm"]),
    ("install nginx, open firewall port 80, and start the service", "Complex: nginx+firewall", ["nginx", "firewall"], ["docker", "git", "python", "systemd", "npm", "ssh"]),
]

def check_skill_selection(optimized_prompt: str, expected_keep: list, expected_drop: list) -> dict:
    kept = [s for s in expected_keep if s.lower() in optimized_prompt.lower()]
    dropped = [s for s in expected_drop if s.lower() in optimized_prompt.lower()]
    return {
        "kept": f"{len(kept)}/{len(expected_keep)}",
        "leaked": dropped,  # skills that should NOT be there
        "score": len(kept) / max(1, len(expected_keep)) * 100,
    }

all_results = {}

for name, port, model, timeout in MODELS:
    print(f"\n{'='*70}")
    print(f"  {name} (port {port})")
    print(f"{'='*70}")

    results = []
    for prompt, desc, exp_keep, exp_drop in TASKS:
        ctx = (f"USER PROMPT:\n{prompt}\n\nMEMORY:\nUser prefers bash shell. OS is Linux.\n\n"
               f"SKILLS:\n{SKILLS}\n\nDOCS:\n\nPLAN:\n")

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": ctx},
            ],
            "temperature": 0.2,
            "max_tokens": 512,
        }

        t0 = time.time()
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=timeout)
            data = json.loads(resp.read())
            text = data["choices"][0]["message"]["content"].strip()

            js = text.find("{")
            je = text.rfind("}")
            if js >= 0 and je > js:
                parsed = json.loads(text[js:je+1])
            else:
                parsed = {"prompt": prompt, "changes": [], "removed": []}

            elapsed = time.time() - t0
            orig_t = len(ctx) // 4
            opt_t = len(parsed.get("prompt", "")) // 4
            savings = max(0, (orig_t - opt_t) / max(1, orig_t) * 100)
            opt_prompt = parsed.get("prompt", "")

            skill_check = check_skill_selection(opt_prompt, exp_keep, exp_drop)
            changes = len(parsed.get("changes", []))
            removed = len(parsed.get("removed", []))

            results.append({
                "desc": desc, "ok": True, "time": round(elapsed, 1),
                "savings": round(savings), "changes": changes, "removed": removed,
                "preview": opt_prompt[:100],
                "skill_score": skill_check["score"],
                "skill_kept": skill_check["kept"],
                "skill_leaked": skill_check["leaked"],
            })

            leak_info = ""
            if skill_check["leaked"]:
                leak_info = f" | LEAKED: {', '.join(skill_check['leaked'])}"
            print(f"  [{desc}] {elapsed:.1f}s | {savings:.0f}% | Skills: {skill_check['kept']}{leak_info}")
            print(f"    → {opt_prompt[:120]}")
        except Exception as e:
            elapsed = time.time() - t0
            results.append({
                "desc": desc, "ok": False, "time": round(elapsed, 1),
                "error": str(e)[:80], "skill_score": 0,
            })
            print(f"  [{desc}] FAIL ({elapsed:.1f}s): {e}")

    all_results[name] = results
    ok = [r for r in results if r.get("ok")]
    if ok:
        avg_s = sum(r["savings"] for r in ok) / len(ok)
        avg_t = sum(r["time"] for r in ok) / len(ok)
        avg_sk = sum(r["skill_score"] for r in ok) / len(ok)
        print(f"\n  AVG: {avg_s:.0f}% savings | {avg_t:.1f}s | Skill accuracy: {avg_sk:.0f}%")

# Summary
print(f"\n{'='*70}")
print(f"  SUMMARY")
print(f"{'='*70}")
print(f"  {'Model':<18} {'Savings':>8} {'Time':>7} {'Skill%':>7} {'Changes':>8} {'Result':>7}")
print(f"  {'-'*60}")

for name, results in all_results.items():
    ok = [r for r in results if r.get("ok")]
    if ok:
        avg_s = sum(r["savings"] for r in ok) / len(ok)
        avg_t = sum(r["time"] for r in ok) / len(ok)
        avg_sk = sum(r["skill_score"] for r in ok) / len(ok)
        avg_c = sum(r["changes"] for r in ok) / len(ok)
        print(f"  {name:<18} {avg_s:>7.0f}% {avg_t:>6.1f}s {avg_sk:>6.0f}% {avg_c:>8.1f} {len(ok)}/{len(results):>4}")

# Head-to-head
print(f"\n{'='*70}")
print(f"  HEAD-TO-HEAD")
print(f"{'='*70}")

for i, (prompt, desc, exp_keep, exp_drop) in enumerate(TASKS):
    print(f"\n  [{desc}] '{prompt}'")
    for name in all_results:
        r = all_results[name][i]
        if r.get("ok"):
            leak = f" | LEAK: {', '.join(r['skill_leaked'])}" if r.get("skill_leaked") else ""
            print(f"    {name:<18}: {r['time']:>5}s | {r['savings']:>3}% | Skills: {r['skill_kept']}{leak}")
            print(f"      {r['preview'][:100]}")
        else:
            print(f"    {name:<18}: FAIL")

# Verdict
print(f"\n{'='*70}")
print(f"  VERDICT")
print(f"{'='*70}")

for name, results in all_results.items():
    ok = [r for r in results if r.get("ok")]
    if ok:
        avg_s = sum(r["savings"] for r in ok) / len(ok)
        avg_t = sum(r["time"] for r in ok) / len(ok)
        avg_sk = sum(r["skill_score"] for r in ok) / len(ok)
        avg_c = sum(r["changes"] for r in ok) / len(ok)
        print(f"\n  {name}:")
        print(f"    Speed:       {'FAST' if avg_t < 5 else 'OK' if avg_t < 15 else 'SLOW'} ({avg_t:.1f}s)")
        print(f"    Savings:     {'GOOD' if avg_s > 60 else 'MEDIUM' if avg_s > 30 else 'LOW'} ({avg_s:.0f}%)")
        print(f"    Skill sel:   {'GOOD' if avg_sk > 80 else 'MEDIUM' if avg_sk > 50 else 'POOR'} ({avg_sk:.0f}%)")
        print(f"    Changes:     {'ACTIVE' if avg_c > 0.5 else 'PASSIVE'} ({avg_c:.1f} avg)")
