"""Direct contextualizer test: 4 models, 4 tasks."""
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
Open ports, allow services, block IPs."""

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
    ("Qwen-1.5B-Q8",  11434, "DeepSeek-R1-Distill-Qwen-1.5B-Q8_0.gguf", 40),
    ("Dolphin-Qwen",  11435, "dolphin3.0-qwen2.5-1.5b-q4_k_m.gguf",     30),
    ("Gemma-4-2B",    11436, "google_gemma-4-E2B-it-Q4_K_M.gguf",        60),
    ("Qwen-7B-Q4",    11437, "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",  90),
]

TASKS = [
    ("install nginx", "Simple", ["nginx"]),
    ("setup a docker container for a python web app with nginx reverse proxy", "Complex", ["docker", "python", "nginx"]),
    ("commit changes and push to remote", "Git", ["git"]),
    ("open port 8080 on the firewall then start my python server", "Multi", ["firewall", "python"]),
]

all_results = {}

for name, port, model, timeout in MODELS:
    print(f"\n{'='*60}")
    print(f"  {name} (port {port})")
    print(f"{'='*60}")

    results = []
    for prompt, desc, exp_skills in TASKS:
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

            # Extract JSON
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

            opt_preview = parsed.get("prompt", "")[:90]
            changes = len(parsed.get("changes", []))
            removed = len(parsed.get("removed", []))

            results.append({
                "desc": desc, "ok": True, "time": round(elapsed, 1),
                "savings": round(savings), "changes": changes, "removed": removed,
                "preview": opt_preview,
            })
            print(f"  [{desc}] {elapsed:.1f}s | {savings:.0f}% | +{changes}/-{removed} | {opt_preview}")
        except Exception as e:
            elapsed = time.time() - t0
            results.append({
                "desc": desc, "ok": False, "time": round(elapsed, 1),
                "error": str(e)[:80],
            })
            print(f"  [{desc}] FAIL ({elapsed:.1f}s): {e}")

    all_results[name] = results
    ok = [r for r in results if r.get("ok")]
    if ok:
        avg_s = sum(r["savings"] for r in ok) / len(ok)
        avg_t = sum(r["time"] for r in ok) / len(ok)
        print(f"  AVG: {avg_s:.0f}% savings | {avg_t:.1f}s")

# Summary
print(f"\n{'='*60}")
print(f"  SUMMARY")
print(f"{'='*60}")
print(f"  {'Model':<20} {'Savings':>8} {'Time':>7} {'Changes':>9} {'Result':>8}")
print(f"  {'-'*55}")

for name, results in all_results.items():
    ok = [r for r in results if r.get("ok")]
    if ok:
        avg_s = sum(r["savings"] for r in ok) / len(ok)
        avg_t = sum(r["time"] for r in ok) / len(ok)
        avg_c = sum(r["changes"] for r in ok) / len(ok)
        print(f"  {name:<20} {avg_s:>7.0f}% {avg_t:>6.1f}s {avg_c:>9.1f} {len(ok)}/{len(results):>5}")
    else:
        print(f"  {name:<20} {'FAIL':>8} {'':>7} {'':>9} {0}/{len(results):>5}")

# Verdict
print(f"\n{'='*60}")
print(f"  VERDICT")
print(f"{'='*60}")

ranked = []
for name, results in all_results.items():
    ok = [r for r in results if r.get("ok")]
    if ok:
        avg_s = sum(r["savings"] for r in ok) / len(ok)
        avg_t = sum(r["time"] for r in ok) / len(ok)
        score = avg_s / max(1, avg_t) * 100
        ranked.append((name, avg_s, avg_t, score, len(ok)))

ranked.sort(key=lambda x: x[3], reverse=True)
for i, (name, s, t, score, ok_count) in enumerate(ranked):
    print(f"  #{i+1} {name}: {s:.0f}% savings, {t:.1f}s, score={score:.1f}")
