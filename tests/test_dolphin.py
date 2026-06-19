"""Live integration test — runs the agent against dolphin model."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from delux_agent.config import Config
from delux_agent.agent import Agent
from delux_agent.sidebar import SidebarState, draw_sidebar
from delux_agent.contextualizer import Contextualizer, ContextualizerConfig


MODEL = "dolphin3.0-qwen2.5-1.5b-q4_k_m.gguf"
API = "http://127.0.0.1:11434/v1"


def _make_config(tmpdir: Path) -> Config:
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
        model=MODEL,
        provider="ollama",
        api_base=API,
        api_endpoint=f"{API}/chat/completions",
        api_key=None,
        root=tmpdir,
        memory_file=mem,
        skills_dir=tmpdir / "skills",
        docs_dir=tmpdir / "docs",
        sessions_dir=tmpdir / "sessions",
        testing_dir=tmpdir / "testing",
        lang="en",
        request_timeout=60,
        shell="bash",
    )


def test_agent_echo():
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        config = _make_config(tmpdir)
        agent = Agent(config=config, cwd=tmpdir / "testing", max_steps=3, ephemeral=True)
        result = agent.run_with_result("echo hello_dolphin", verbose=False)

        print(f"\n  Steps: {len(result.steps)}")
        for i, s in enumerate(result.steps):
            ok = not s.result.startswith("ERROR:")
            print(f"    [{i+1}] {s.action.get('action', '?')} => {'✓' if ok else '✗'} {s.result[:80]}")

        assert len(result.steps) > 0
        assert any("SUCCESS" in s.result for s in result.steps)
        print("  PASSED: echo")


def test_agent_write_and_read():
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        config = _make_config(tmpdir)
        agent = Agent(config=config, cwd=tmpdir / "testing", max_steps=6, ephemeral=True)
        result = agent.run_with_result("create file dolphin.txt with content 'hello from dolphin' then read it", verbose=False)

        print(f"\n  Steps: {len(result.steps)}")
        for i, s in enumerate(result.steps):
            ok = not s.result.startswith("ERROR:")
            detail = s.action.get("path", s.action.get("command", ""))[:40]
            print(f"    [{i+1}] {s.action.get('action', '?')} {detail} => {'✓' if ok else '✗'}")

        assert len(result.steps) >= 2
        actions = [s.action.get("action") for s in result.steps]
        assert "write_file" in actions or "shell" in actions
        print("  PASSED: write+read")


def test_agent_with_contextualizer():
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        config = _make_config(tmpdir)

        ctx_cfg = ContextualizerConfig(
            enabled=True,
            model=MODEL,
            provider="ollama",
            api_base=API,
            api_endpoint=f"{API}/chat/completions",
        )
        ctx = Contextualizer(config, ctx_cfg)
        skills = "--- skill:nginx ---\nInstall and configure nginx on Fedora/Debian"

        result = ctx.contextualize(
            user_prompt="install nginx",
            memory="",
            skills=skills,
            docs="",
        )

        print(f"\n  Original tokens: {result.original_tokens}")
        print(f"  Optimized tokens: {result.optimized_tokens}")
        print(f"  Savings: {result.savings_pct:.1f}%")

        assert len(result.prompt) > 0
        print("  PASSED: contextualizer with dolphin")


def test_agent_sidebar():
    sb = SidebarState()
    sb.visible = True
    sb.model_name = MODEL
    sb.cwd = "/home/user/project"
    sb.lang = "en"
    sb.running = True
    sb.current_action = "shell: dnf install nginx"
    sb.plan_progress = "2/4"
    sb.plan_step = "Step 2: install nginx"
    sb.plan_steps_list = [
        {"id": 1, "desc": "update package list", "status": "done"},
        {"id": 2, "desc": "install nginx", "status": "running"},
        {"id": 3, "desc": "start service", "status": "pending"},
        {"id": 4, "desc": "verify", "status": "pending"},
    ]

    draw_sidebar(sb)
    print("\n  PASSED: sidebar with dolphin model name")


def test_agent_plan_create_and_verify():
    """Test agent with a plan: create dir, write file, verify."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        config = _make_config(tmpdir)

        from delux_agent.ide import AgentPlan, PlanStep

        plan = AgentPlan(
            prompt="create project structure",
            summary="create a simple project with a file and verify",
            steps=[
                PlanStep(id=1, description="Create a directory named project_alpha"),
                PlanStep(id=2, description="Write a file main.py inside with content 'print(hello)'"),
                PlanStep(id=3, description="Verify the file exists using ls"),
            ],
        )

        agent = Agent(
            config=config,
            cwd=tmpdir / "testing",
            max_steps=8,
            ephemeral=True,
            plan=plan,
            run_counter=1,
        )

        result = agent.run_with_result("create project structure", verbose=False)

        print(f"\n  Steps: {len(result.steps)}")
        print(f"  Plan complete: {agent.plan_executor.plan_complete}")
        print(f"  Plan progress: {agent.plan_executor.progress_str()}")
        for i, s in enumerate(result.steps):
            ok = not s.result.startswith("ERROR:")
            print(f"    [{i+1}] {s.action.get('action', '?')} => {'✓' if ok else '✗'} {s.result[:80]}")

        print("  PASSED: plan execution")


if __name__ == "__main__":
    tests = [
        ("Agent echo", test_agent_echo),
        ("Agent write+read", test_agent_write_and_read),
        ("Contextualizer with dolphin", test_agent_with_contextualizer),
        ("Sidebar render", test_agent_sidebar),
        ("Agent plan (3 steps)", test_agent_plan_create_and_verify),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        print(f"\n{'='*40}")
        print(f"  Model: {MODEL}")
        print(f"  Test: {name}")
        print(f"{'='*40}")
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"\n  FAILED: {name}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*50}")
    print(f"  Dolphin live tests: {passed} passed, {failed} failed out of {len(tests)}")
    print(f"{'='*50}")
    sys.exit(1 if failed > 0 else 0)
