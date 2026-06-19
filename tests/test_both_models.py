"""Live tests: remote gemini-pro (10.0.0.16:5000) vs local qwen (127.0.0.1:11434)."""
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


MODELS = [
    {
        "name": "remote-gemma4",
        "model": "gemini-pro",
        "api_base": "http://10.0.0.16:5000/v1",
        "api_endpoint": "http://10.0.0.16:5000/v1/chat/completions",
        "api_key": None,
        "timeout": 90,
        "shell": "sh",
    },
    {
        "name": "local-qwen",
        "model": "dolphin3.0-qwen2.5-1.5b-q4_k_m.gguf",
        "api_base": "http://127.0.0.1:11434/v1",
        "api_endpoint": "http://127.0.0.1:11434/v1/chat/completions",
        "api_key": None,
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
        api_key=m["api_key"],
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
            model_cfg["api_key"],
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
            return f"EMPTY RESPONSE"
        import json
        parsed = json.loads(result.text.strip())
        return f"OK: {parsed.get('action', '?')}"
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

        skills = "--- skill:nginx ---\nInstall and configure nginx\n--- skill:git ---\nGit operations"
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
            "changes": result.changes[:2],
        }


def run_tests_for_model(model_cfg: dict):
    name = model_cfg["name"]
    print(f"\n{'='*60}")
    print(f"  Testing: {name} ({model_cfg['model']})")
    print(f"  Endpoint: {model_cfg['api_endpoint']}")
    print(f"{'='*60}")

    results = {}

    # Test 1: JSON format
    print(f"\n  [1/4] JSON action format...")
    r = test_llm_json_format(model_cfg)
    print(f"    {r}")
    results["json_format"] = r

    # Test 2: Echo
    print(f"  [2/4] Agent echo command...")
    r = test_agent_echo(model_cfg)
    print(f"    Steps: {r['steps']} ({r['ok']} ok) | Time: {r['elapsed']}")
    for d in r["details"]:
        print(f"      {d['action']} {'✓' if d['ok'] else '✗'} {d['result'][:60]}")
    results["echo"] = r

    # Test 3: Write file
    print(f"  [3/4] Agent write+read file...")
    r = test_agent_write_file(model_cfg)
    print(f"    Steps: {r['steps']} | Time: {r['elapsed']}")
    for d in r["details"]:
        print(f"      {d['action']} {'✓' if d['ok'] else '✗'} {d['result'][:60]}")
    results["write_file"] = r

    # Test 4: Contextualizer
    print(f"  [4/4] Contextualizer optimization...")
    r = test_contextualizer(model_cfg)
    print(f"    Tokens: {r['original_tokens']} -> {r['optimized_tokens']} | Savings: {r['savings_pct']} | Time: {r['elapsed']}")
    results["contextualizer"] = r

    return results


if __name__ == "__main__":
    all_results = {}

    for model_cfg in MODELS:
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
    print(f"\n  {'Test':<25} {'Remote Gemma4':<20} {'Local Qwen':<20}")
    print(f"  {'-'*65}")

    for test_name in ["json_format", "echo", "write_file", "contextualizer"]:
        vals = []
        for m in MODELS:
            r = all_results.get(m["name"], {}).get(test_name, {})
            if isinstance(r, str):
                vals.append(r[:18])
            elif isinstance(r, dict):
                if test_name == "echo":
                    vals.append(f"{r.get('steps',0)} steps, {r.get('elapsed','?')}")
                elif test_name == "write_file":
                    vals.append(f"{r.get('steps',0)} steps, {r.get('elapsed','?')}")
                elif test_name == "contextualizer":
                    vals.append(f"{r.get('savings_pct','?')} savings")
                else:
                    vals.append(str(r)[:18])
            else:
                vals.append("N/A")

        print(f"  {test_name:<25} {vals[0]:<20} {vals[1]:<20}")

    print(f"\n  {'='*60}")
