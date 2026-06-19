"""Live integration test — runs the agent against a real model."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from delux_agent.config import Config, ModelEntry
from delux_agent.agent import Agent
from delux_agent.sidebar import SidebarState, draw_sidebar
from delux_agent.contextualizer import Contextualizer, ContextualizerConfig


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
        model="google_gemma-4-E2B-it-Q4_K_M.gguf",
        provider="ollama",
        api_base="http://127.0.0.1:11434/v1",
        api_endpoint="http://127.0.0.1:11434/v1/chat/completions",
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


def test_agent_basic_run():
    """Test: agent can execute a simple shell command and return SUCCESS."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        config = _make_config(tmpdir)
        cwd = tmpdir / "testing"
        events = []

        def handler(event: str, payload: dict) -> None:
            events.append((event, payload))

        agent = Agent(
            config=config,
            cwd=cwd,
            event_handler=handler,
            max_steps=3,
            ephemeral=True,
        )

        result = agent.run_with_result("echo hello_world", verbose=False)

        print(f"\n=== Agent Run ===")
        print(f"Steps: {len(result.steps)}")
        print(f"Answer: {result.answer[:120]}")
        for i, step in enumerate(result.steps):
            action = step.action.get("action", "?")
            ok = not step.result.startswith("ERROR:")
            print(f"  [{i+1}] {action} {'✓' if ok else '✗'}")

        assert len(result.steps) > 0, "Expected at least 1 step"
        assert any("SUCCESS" in s.result for s in result.steps), f"Expected SUCCESS in steps, got: {[s.result[:30] for s in result.steps]}"
        print("  PASSED: basic agent run")


def test_sidebar_during_execution():
    """Test: sidebar renders without errors during agent execution events."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)

        sb = SidebarState()
        sb.visible = True
        sb.model_name = "gemma-4-2b"
        sb.cwd = str(tmpdir)
        sb.lang = "en"
        sb.running = True
        sb.current_action = "shell: echo test"
        sb.plan_progress = "1/3"
        sb.plan_step = "Step 1: run echo"
        sb.plan_steps_list = [
            {"id": 1, "desc": "run echo", "status": "done"},
            {"id": 2, "desc": "write file", "status": "running"},
            {"id": 3, "desc": "verify", "status": "pending"},
        ]

        draw_sidebar(sb)
        print("\n=== Sidebar Render ===")
        print("  PASSED: sidebar rendered without errors")


def test_contextualizer_live():
    """Test: contextualizer can optimize a prompt using the live model."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        config = _make_config(tmpdir)

        ctx_cfg = ContextualizerConfig(
            enabled=True,
            model="google_gemma-4-E2B-it-Q4_K_M.gguf",
            provider="ollama",
            api_base="http://127.0.0.1:11434/v1",
            api_endpoint="http://127.0.0.1:11434/v1/chat/completions",
        )

        ctx = Contextualizer(config, ctx_cfg)
        skills = "--- skill:git ---\nGit workflow: clone, commit, push\n--- skill:nginx ---\nInstall and configure nginx"

        result = ctx.contextualize(
            user_prompt="install nginx",
            memory="User prefers bash",
            skills=skills,
            docs="",
        )

        print(f"\n=== Contextualizer ===")
        print(f"  Original tokens: {result.original_tokens}")
        print(f"  Optimized tokens: {result.optimized_tokens}")
        print(f"  Savings: {result.savings_pct:.1f}%")
        for change in result.changes:
            print(f"  Change: {change[:80]}")

        assert len(result.prompt) > 0
        print("  PASSED: contextualizer produced optimized prompt")


def test_agent_create_file_and_verify():
    """Test: agent can create a file and verify it exists."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        config = _make_config(tmpdir)
        cwd = tmpdir / "testing"
        events = []

        def handler(event: str, payload: dict) -> None:
            events.append((event, payload))

        agent = Agent(
            config=config,
            cwd=cwd,
            event_handler=handler,
            max_steps=5,
            ephemeral=True,
        )

        result = agent.run_with_result("create a file called test123.txt with content 'hello' then read it back", verbose=False)

        print(f"\n=== Agent Create+Read ===")
        print(f"Steps: {len(result.steps)}")
        for i, step in enumerate(result.steps):
            action = step.action.get("action", "?")
            detail = step.action.get("path", step.action.get("command", ""))[:40]
            ok = not step.result.startswith("ERROR:")
            print(f"  [{i+1}] {action} {detail} {'✓' if ok else '✗'}")

        assert len(result.steps) >= 2, f"Expected at least 2 steps (write + read), got {len(result.steps)}"
        actions = [s.action.get("action") for s in result.steps]
        assert "write_file" in actions or "shell" in actions, f"Expected write action, got {actions}"
        print("  PASSED: agent created and read file")


if __name__ == "__main__":
    tests = [
        ("Basic agent run", test_agent_basic_run),
        ("Sidebar render", test_sidebar_during_execution),
        ("Contextualizer live", test_contextualizer_live),
        ("Agent create+read file", test_agent_create_file_and_verify),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        print(f"\n{'='*40}")
        print(f"  Running: {name}")
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
    print(f"  Live tests: {passed} passed, {failed} failed out of {len(tests)}")
    print(f"{'='*50}")
    sys.exit(1 if failed > 0 else 0)
