from __future__ import annotations

from delux_agent.plan_executor import PlanExecution, PlanExecutor, PlanStepStatus


def _make_plan_execution(summary: str, steps: list[str]) -> PlanExecution:
    exec_id = "plan1"
    execution = PlanExecution(
        exec_id=exec_id,
        prompt="test prompt",
        summary=summary,
        steps=[PlanStepStatus(id=i + 1, description=s) for i, s in enumerate(steps)],
    )
    return execution


class FakeAgentPlan:
    def __init__(self, steps_data: list[dict]) -> None:
        self.prompt = "test"
        self.summary = "test plan"
        self.steps = [_PlanStep(**s) for s in steps_data]


class _PlanStep:
    def __init__(self, id: int, description: str, detail: str = "") -> None:
        self.id = id
        self.description = description
        self.detail = detail


def test_next_step_returns_first_pending():
    exec_plan = _make_plan_execution("test", ["step1", "step2", "step3"])
    step = exec_plan.next_step()
    assert step is not None
    assert step.id == 1
    assert step.status == "pending"


def test_next_step_skips_done_steps():
    exec_plan = _make_plan_execution("test", ["step1", "step2", "step3"])
    exec_plan.mark_done(1, True)
    exec_plan.mark_done(2, True)

    step = exec_plan.next_step()
    assert step is not None
    assert step.id == 3


def test_next_step_returns_none_when_all_done():
    exec_plan = _make_plan_execution("test", ["step1", "step2"])
    exec_plan.mark_done(1, True)
    exec_plan.mark_done(2, True)

    assert exec_plan.next_step() is None
    assert exec_plan.is_complete()


def test_mark_done_updates_status():
    exec_plan = _make_plan_execution("test", ["step1"])
    exec_plan.mark_done(1, True)
    assert exec_plan.steps[0].status == "done"


def test_mark_done_with_failure():
    exec_plan = _make_plan_execution("test", ["step1"])
    exec_plan.mark_done(1, False)
    assert exec_plan.steps[0].status == "failed"


def test_mark_skipped():
    exec_plan = _make_plan_execution("test", ["step1", "step2"])
    exec_plan.mark_skipped(1, "not needed")
    assert exec_plan.steps[0].status == "skipped"
    assert "not needed" in exec_plan.steps[0].detail


def test_is_complete_with_skipped():
    exec_plan = _make_plan_execution("test", ["step1", "step2"])
    exec_plan.mark_done(1, True)
    exec_plan.mark_skipped(2, "already done")
    assert exec_plan.is_complete()


def test_is_complete_false_with_failed():
    exec_plan = _make_plan_execution("test", ["step1", "step2"])
    exec_plan.mark_done(1, True)
    exec_plan.mark_done(2, False)

    step = exec_plan.next_step()
    assert step is not None
    assert step.id == 2
    assert step.status == "failed"


def test_progress_str():
    exec_plan = _make_plan_execution("test", ["step1", "step2", "step3", "step4"])
    exec_plan.mark_done(1, True)
    exec_plan.mark_done(2, True)
    assert exec_plan.progress_str() == "2/4"

    exec_plan.mark_skipped(3, "n/a")
    assert exec_plan.progress_str() == "3/4"


def test_build_step_instruction():
    exec_plan = _make_plan_execution("test", ["create dir", "write file", "verify"])
    step = exec_plan.next_step()

    instruction = exec_plan.build_step_instruction(step)
    assert "PLAN STEP" in instruction
    assert "create dir" in instruction
    assert "skip_step" in instruction


def test_build_completion_message():
    exec_plan = _make_plan_execution("test plan", ["step1", "step2"])
    exec_plan.mark_done(1, True)
    exec_plan.mark_skipped(2, "not needed")

    msg = exec_plan.build_completion_message()
    assert "test plan" in msg
    assert "step1" in msg
    assert "step2" in msg


def test_plan_executor_from_fake_plan():
    plan = FakeAgentPlan([
        {"id": 1, "description": "create"},
        {"id": 2, "description": "write"},
        {"id": 3, "description": "verify"},
    ])

    exec = PlanExecutor(plan, exec_counter=1)
    assert exec.in_progress
    assert not exec.plan_complete

    step = exec.get_current_step()
    assert step is not None
    assert step.id == 1

    exec.record_done(1, True)
    assert exec.progress_str() == "1/3"


def test_plan_executor_can_finalize():
    plan = FakeAgentPlan([
        {"id": 1, "description": "step1"},
        {"id": 2, "description": "step2"},
    ])
    exec = PlanExecutor(plan, exec_counter=1)

    assert not exec.can_finalize()

    exec.record_done(1, True)
    exec.record_done(2, True)
    assert exec.can_finalize()


def test_plan_executor_skip_all_steps():
    plan = FakeAgentPlan([
        {"id": 1, "description": "step1"},
        {"id": 2, "description": "step2"},
    ])
    exec = PlanExecutor(plan, exec_counter=1)

    exec.record_skip(1, "unnecessary")
    exec.record_skip(2, "also unnecessary")
    assert exec.can_finalize()


def test_plan_executor_with_empty_plan():
    plan = FakeAgentPlan([])
    exec = PlanExecutor(plan, exec_counter=1)

    assert exec.execution is None
    assert exec.can_finalize()
    assert exec.plan_complete


def test_plan_executor_max_steps_simulation():
    """Simulate scenario where max steps reached before plan completion."""
    plan = FakeAgentPlan([
        {"id": 1, "description": "step1"},
        {"id": 2, "description": "step2"},
        {"id": 3, "description": "step3"},
        {"id": 4, "description": "step4"},
    ])
    exec = PlanExecutor(plan, exec_counter=1)

    exec.record_done(1, True)
    exec.record_done(2, False)

    assert exec.in_progress
    assert not exec.plan_complete

    step = exec.get_current_step()
    assert step is not None
    assert step.id == 2
    assert step.status == "failed"

    summary = exec.finalize_summary()
    assert "plan" in summary.lower() or "step" in summary.lower()


def test_step_by_id():
    exec_plan = _make_plan_execution("test", ["alpha", "beta", "gamma"])
    step = exec_plan.step_by_id(2)
    assert step is not None
    assert step.description == "beta"
    assert exec_plan.step_by_id(99) is None
