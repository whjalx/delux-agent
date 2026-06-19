"""Local model comparison: Llama 3.2 1B vs Dolphin Qwen 2.5 1.5B."""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from delux_agent.config import Config
from delux_agent.agent import Agent
from delux_agent.sidebar import SidebarState, draw_sidebar
from delux_agent.contextualizer import Contextualizer, ContextualizerConfig
from delux_agent.llm import chat_completion


LOCAL_MODELS = [
    {
        "name": "llama-local",
        "model": "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        "api_base": "http://127.0.0.1:11434/v1",
        "api_endpoint": "http://127.0.0.1:11434/v1/chat/completions",
        "timeout": 60,
        "shell": "sh",
    },
    {
        "name": "qwen-local",
        "model": "dolphin3.0-qwen2.5-1.5b-q4_k_m.gguf",
        "api_base": "http://127.0.0.1:11434/v1",
        "api_endpoint": "http://127.0.0.1:11434/v1/chat/completions",
        "timeout": 60,
        "shell": "sh",
    },
]


def _make_config(tmpdir: Path, m: dict) -> Config:
    (tmpdir / "skills").mkdir(exist_ok=True)
    (tmpdir / "docs").mkdir(exist_ok=True)
    (tmpdir / "sessions").mkdir(exist_ok=True)
    (tmpdir / "testing").mkdir(exist_ok=True)
    mem_dir = tmpdir / "memory"
    mem_dir.mkdir(exist_ok=True)
    mem = mem_dir / "memory.md"
    if not mem.exists():
        mem.write_text("", encoding="utf-8")
    return Config(
        model=m["model"],
        provider="openai",
        api_base=m["api_base"],
        api_endpoint=m["api_endpoint"],
        api_key=None,
        root=tmpdir,
        memory_file=mem,
        skills_dir=tmpdir / "skills",
        docs_dir=tmpdir / "docs",
        sessions_dir=tmpdir / "sessions",
        testing_dir=tmpdir / "testing",
        lang="en",
        request_timeout=m["timeout"],
        shell=m["shell"],
    )


def test_llm_json_format(model_cfg: dict) -> str:
    """Test: model returns valid JSON action."""
    try:
        result = chat_completion(
            model_cfg["api_base"],
            None,
            model_cfg["model"],
            [
                {"role": "system", "content": 'Return ONLY a JSON action: {"action":"shell","command":"echo hello"}'},
                {"role": "user", "content": "echo hello"},
            ],
            model_cfg["api_endpoint"],
            timeout=30,
            stream=False,
        )
        if not result.text.strip():
            return "EMPTY RESPONSE"
        import json
        parsed = json.loads(result.text.strip())
        return f"OK: action={parsed.get('action', '?')}"
    except Exception as e:
        return f"FAIL: {e}"


def test_agent_echo(model_cfg: dict) -> dict:
    """Test: agent executes echo command."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        config = _make_config(tmpdir, model_cfg)
        agent = Agent(config=config, cwd=tmpdir / "testing", max_steps=3, ephemeral=True)

        t0 = time.time()
        result = agent.run_with_result("echo hello_agent", verbose=False)
        elapsed = time.time() - t0

        steps_ok = sum(1 for s in result.steps if not s.result.startswith("ERROR:"))
        return {
            "steps": len(result.steps),
            "ok": steps_ok,
            "elapsed": f"{elapsed:.1f}s",
            "answer": result.answer[:100],
            "details": [
                {
                    "action": s.action.get("action", "?"),
                    "ok": not s.result.startswith("ERROR:"),
                    "result": s.result[:80],
                }
                for s in result.steps[:5]
            ],
        }


def test_agent_write_file(model_cfg: dict) -> dict:
    """Test: agent creates and reads a file."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        config = _make_config(tmpdir, model_cfg)
        agent = Agent(config=config, cwd=tmpdir / "testing", max_steps=5, ephemeral=True)

        t0 = time.time()
        result = agent.run_with_result("write a file named test_output.txt with the text 'hello file test' then verify it exists", verbose=False)
        elapsed = time.time() - t0

        return {
            "steps": len(result.steps),
            "elapsed": f"{elapsed:.1f}s",
            "answer": result.answer[:100],
            "details": [
                {
                    "action": s.action.get("action", "?"),
                    "ok": not s.result.startswith("ERROR:"),
                    "result": s.result[:80],
                }
                for s in result.steps[:5]
            ],
        }


def test_agent_list_dir(model_cfg: dict) -> dict:
    """Test: agent lists directory contents."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        config = _make_config(tmpdir, model_cfg)
        agent = Agent(config=config, cwd=tmpdir / "testing", max_steps=3, ephemeral=True)

        t0 = time.time()
        result = agent.run_with_result("list files in the current directory", verbose=False)
        elapsed = time.time() - t0

        return {
            "steps": len(result.steps),
            "ok": sum(1 for s in result.steps if not s.result.startswith("ERROR:")),
            "elapsed": f"{elapsed:.1f}s",
            "answer": result.answer[:100],
            "details": [
                {
                    "action": s.action.get("action", "?"),
                    "ok": not s.result.startswith("ERROR:"),
                    "result": s.result[:80],
                }
                for s in result.steps[:5]
            ],
        }


def test_contextualizer(model_cfg: dict) -> dict:
    """Test: contextualizer optimizes prompt."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        config = _make_config(tmpdir, model_cfg)

        ctx_cfg = ContextualizerConfig(
            enabled=True,
            model=model_cfg["model"],
            provider="openai",
            api_base=model_cfg["api_base"],
            api_endpoint=model_cfg["api_endpoint"],
        )
        ctx = Contextualizer(config, ctx_cfg)

        skills = "--- skill:nginx ---\nInstall and configure nginx\n--- skill:git ---\nGit operations\n--- skill:docker ---\nDocker containers"
        t0 = time.time()
        result = ctx.contextualize(
            user_prompt="install nginx",
            memory="",
            skills=skills,
            docs="",
        )
        elapsed = time.time() - t0

        return {
            "elapsed": f"{elapsed:.1f}s",
            "original_tokens": result.original_tokens,
            "optimized_tokens": result.optimized_tokens,
            "savings_pct": f"{result.savings_pct:.1f}%",
            "changes": result.changes[:3],
        }


def run_tests_for_model(model_cfg: dict):
    name = model_cfg["name"]
    print(f"\n{'='*60}")
    print(f"  Testing: {name}")
    print(f"  Model: {model_cfg['model']}")
    print(f"  Endpoint: {model_cfg['api_endpoint']}")
    print(f"{'='*60}")

    results = {}

    print(f"\n  [1/5] JSON action format...")
    r = test_llm_json_format(model_cfg)
    print(f"    {r}")
    results["json_format"] = r

    print(f"  [2/5] Agent echo...")
    r = test_agent_echo(model_cfg)
    print(f"    Steps: {r['steps']} ({r['ok']} ok) | Time: {r['elapsed']}")
    for d in r["details"]:
        print(f"      {d['action']} {'✓' if d['ok'] else '✗'} {d['result'][:60]}")
    results["echo"] = r

    print(f"  [3/5] Agent write+read file...")
    r = test_agent_write_file(model_cfg)
    print(f"    Steps: {r['steps']} | Time: {r['elapsed']}")
    for d in r["details"]:
        print(f"      {d['action']} {'✓' if d['ok'] else '✗'} {d['result'][:60]}")
    results["write_file"] = r

    print(f"  [4/5] Agent list directory...")
    r = test_agent_list_dir(model_cfg)
    print(f"    Steps: {r['steps']} ({r['ok']} ok) | Time: {r['elapsed']}")
    for d in r["details"]:
        print(f"      {d['action']} {'✓' if d['ok'] else '✗'} {d['result'][:60]}")
    results["list_dir"] = r

    print(f"  [5/5] Contextualizer optimization...")
    r = test_contextualizer(model_cfg)
    print(f"    Tokens: {r['original_tokens']} -> {r['optimized_tokens']} | Savings: {r['savings_pct']} | Time: {r['elapsed']}")
    for c in r["changes"]:
        print(f"      - {c[:80]}")
    results["contextualizer"] = r

    return results


if __name__ == "__main__":
    all_results = {}

    for model_cfg in LOCAL_MODELS:
        try:
            all_results[model_cfg["name"]] = run_tests_for_model(model_cfg)
        except Exception as e:
            print(f"\n  ERROR: {model_cfg['name']} — {e}")
            import traceback
            traceback.print_exc()
            all_results[model_cfg["name"]] = {"error": str(e)}

    # Summary table
    print(f"\n{'='*60}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'='*60}")
    print(f"\n  {'Test':<25} {'Llama 3.2 1B':<22} {'Dolphin Qwen 1.5B':<22}")
    print(f"  {'-'*69}")

    for test_name in ["json_format", "echo", "write_file", "list_dir", "contextualizer"]:
        vals = []
        for m in LOCAL_MODELS:
            r = all_results.get(m["name"], {}).get(test_name, {})
            if isinstance(r, str):
                vals.append(r[:20])
            elif isinstance(r, dict):
                if test_name in ("echo", "list_dir"):
                    vals.append(f"{r.get('steps',0)}s {r.get('ok',0)}ok {r.get('elapsed','?')}")
                elif test_name == "write_file":
                    vals.append(f"{r.get('steps',0)}s {r.get('elapsed','?')}")
                elif test_name == "contextualizer":
                    vals.append(f"{r.get('savings_pct','?')} {r.get('elapsed','?')}")
                else:
                    vals.append(str(r)[:20])
            else:
                vals.append("N/A")

        print(f"  {test_name:<25} {vals[0]:<22} {vals[1]:<22}")

    print(f"\n  {'='*60}")
