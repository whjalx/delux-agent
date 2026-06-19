import time
import json
import os
import sys

sys.path.append(os.getcwd())

from delux_agent.contextualizer import Contextualizer, ContextualizerConfig
from delux_agent.config import load_config

PORTS = [11434, 11435, 11436]

# Ruido que el pre-filtro NO podrá borrar fácilmente porque contiene palabras técnicas
TECH_NOISE = """
System administration involves monitoring. Users often install packages. 
Nginx is a server. Git is for version control. Python is a language. 
The database is somewhere. Port 22 is for SSH. 
This text is designed to look relevant but it is actually noise.
""" * 10 

TEST_CASES = [
    {
        "id": "EASY",
        "prompt": "ls -la",
        "memory": f"Shell: bash. Server at 192.168.1.1. {TECH_NOISE}",
        "skills": "--- skill:sys-health: CPU report\n--- skill:git-summary: Git dashboard",
        "gold": ["ls -la", "192.168.1.1"],
        "noise": ["SSH", "version control", "Python"]
    },
    {
        "id": "MEDIUM",
        "prompt": "Fix the nginx port 80 error",
        "memory": f"OS: Fedora. Nginx config at /etc/nginx/nginx.conf. Port is 80. {TECH_NOISE}",
        "skills": "--- skill:net-check: check network\n--- skill:search-expert: find files",
        "gold": ["/etc/nginx/nginx.conf", "Fedora", "net-check"],
        "noise": ["SSH", "Python", "version control"]
    },
    {
        "id": "ULTRA_PLAN",
        "prompt": "Proceed with step 3 of the database migration.",
        "plan": """Step 1: Export (COMPLETED)\nStep 2: Connect (FAILED: Error 111 connection refused on 10.0.0.5)\nStep 3: Fix .env (CURRENT)""",
        "memory": f"DB is Postgres. Host is 10.0.0.5. User likes blue. {TECH_NOISE}",
        "skills": "--- skill:pg-run: SQL tool\n--- skill:play-music: Music tool",
        "gold": ["Error 111", "10.0.0.5", "pg-run", "Step 3"],
        "noise": ["blue", "SSH", "Nginx"]
    }
]

def run_test():
    base_config = load_config()
    final_results = []

    for port in PORTS:
        import urllib.request
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/v1/models") as r:
                m_name = json.loads(r.read())["data"][0]["id"]
        except:
            m_name = f"Port-{port}"

        print(f"\n🧠 [FORCED LLM TEST: {m_name}]")
        
        ctx_cfg = ContextualizerConfig(
            enabled=True,
            model="default",
            api_base=f"http://localhost:{port}/v1",
            use_heuristic_prefilter=False # DESACTIVADO PARA EL TEST
        )
        ctx = Contextualizer(base_config, ctx_cfg)
        
        scores = []
        for tc in TEST_CASES:
            print(f"  > Case {tc['id']}...", end="", flush=True)
            start = time.time()
            
            res = ctx.contextualize(
                user_prompt=tc["prompt"],
                memory=tc["memory"],
                skills=tc["skills"],
                docs="",
                plan_context=tc.get("plan", "")
            )
            
            duration = time.time() - start
            
            # Scoring
            gold_found = sum(1 for g in tc["gold"] if g.lower() in res.prompt.lower())
            recall = (gold_found / len(tc["gold"])) * 60
            
            noise_found = sum(1 for n in tc["noise"] if n.lower() in res.prompt.lower())
            precision = 30 - (noise_found / len(tc["noise"])) * 30
            
            latency = 10 if duration < 10 else (5 if duration < 25 else 0)
            
            total = recall + precision + latency
            scores.append(total)
            print(f" Done ({total:.1f} pts) in {duration:.2f}s | Savings: {res.savings_pct:.1f}%")

        final_results.append({"model": m_name, "score": sum(scores)/len(scores)})

    return final_results

if __name__ == "__main__":
    report = run_test()
    print("\n" + "="*40)
    for r in report:
        print(f"| {r['model']:30} | {r['score']:5.1f} |")
    print("="*40)
