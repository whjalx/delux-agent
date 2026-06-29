from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlanStepStatus:
    """Status of a single plan step."""
    id: int
    description: str
    detail: str = ""
    status: str = "pending"  # pending | running | done | failed | skipped


@dataclass
class PlanExecution:
    """In-memory plan for a single prompt execution. Lives only during the run."""
    exec_id: str              # "plan1", "plan2", etc.
    prompt: str               # original user prompt
    summary: str              # 1-line summary
    steps: list[PlanStepStatus] = field(default_factory=list)
    current_idx: int = 0      # index into steps list
    in_progress: bool = True  # flag: True while steps remain

    def next_step(self) -> PlanStepStatus | None:
        """Return the next pending/failed step, or None if all done."""
        for i in range(self.current_idx, len(self.steps)):
            s = self.steps[i]
            if s.status in ("pending", "failed"):
                self.current_idx = i
                return s
        self.in_progress = False
        return None

    def mark_done(self, step_id: int, ok: bool) -> None:
        for s in self.steps:
            if s.id == step_id:
                s.status = "done" if ok else "failed"

    def mark_skipped(self, step_id: int, reason: str = "") -> None:
        for s in self.steps:
            if s.id == step_id:
                s.status = "skipped"
                if reason:
                    s.detail = f"skipped: {reason}"

    def step_by_id(self, step_id: int) -> PlanStepStatus | None:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None

    def is_complete(self) -> bool:
        """True when no more pending/failed steps remain."""
        return all(s.status in ("done", "skipped") for s in self.steps)

    def progress_str(self) -> str:
        done = sum(1 for s in self.steps if s.status in ("done", "skipped"))
        total = len(self.steps)
        return f"{done}/{total}"

    def build_step_instruction(self, step: PlanStepStatus) -> str:
        remaining = [s for s in self.steps if s.status == "pending"]
        after = [s for s in self.steps if s.status in ("done", "skipped", "failed")]

        lines: list[str] = []
        lines.append(f"!!! PLAN IN PROGRESS !!!")
        lines.append(f"CURRENT STEP ({step.id}/{len(self.steps)}): {step.description}")
        if step.detail:
            lines.append(f"SPECIFICS: {step.detail}")
        lines.append("")
        progress = self.progress_str()
        lines.append(f"Progress: {progress}")
        if after:
            descs = [f"#{s.id} {s.description}" for s in after[:5]]
            lines.append(f"Completed: {'; '.join(descs)}")
        if len(remaining) > 1:
            lines.append(f"Remaining: {len(remaining) - 1} more steps")
        else:
            lines.append("This is the last step.")
        lines.append("")
        lines.append("ACTION REQUIRED:")
        lines.append("- Execute this step using the appropriate tool (shell, write_file, search_files, etc.)")
        lines.append("- If the step is already done by previous actions, skip it:")
        lines.append("  <action>skip_step</action>\n  <step_id>" + str(step.id) + "</step_id>\n  <reason>why</reason>")
        lines.append("- If this step fails 3 times consecutively, skip it and move on.")
        lines.append("- Do NOT use final until ALL steps are done/skipped.")
        return "\n".join(lines)

    def build_completion_message(self) -> str:
        """Build the final summary when the plan is complete."""
        lines: list[str] = []
        lines.append(f"Plan '{self.summary}' completed ({self.progress_str()}):")
        for s in self.steps:
            icon = {"done": "\u2705", "skipped": "\u23ed\ufe0f", "failed": "\u274c"}.get(s.status, "?")
            lines.append(f"  {icon} Step {s.id}: {s.description} ({s.status})")
            if s.detail:
                lines.append(f"     {s.detail}")
        return "\n".join(lines)

    def step_summary(self) -> str:
        """One-line overview of all steps for context."""
        parts: list[str] = []
        for s in self.steps:
            if s.status == "done":
                parts.append(f"[done] {s.description}")
            elif s.status == "skipped":
                parts.append(f"[skipped] {s.description}")
            elif s.status == "failed":
                parts.append(f"[failed] {s.description}")
            else:
                parts.append(f"[next] {s.description}")
        return " | ".join(parts)


class PlanExecutor:
    """Manages plan execution state. Lives in memory during a single run."""

    def __init__(self, plan: AgentPlan | None, exec_counter: int) -> None:
        self.exec_counter = exec_counter
        self.execution: PlanExecution | None = None
        if plan and hasattr(plan, "steps") and plan.steps:
            exec_id = f"plan{exec_counter}"
            self.execution = PlanExecution(
                exec_id=exec_id,
                prompt=getattr(plan, "prompt", ""),
                summary=getattr(plan, "summary", ""),
                steps=[
                    PlanStepStatus(id=s.id, description=s.description, detail=getattr(s, "detail", ""))
                    for s in plan.steps
                ],
            )

    @property
    def in_progress(self) -> bool:
        return self.execution is not None and self.execution.in_progress

    @property
    def plan_complete(self) -> bool:
        if self.execution is None:
            return True
        return self.execution.is_complete()

    def get_current_step(self) -> PlanStepStatus | None:
        """Get the next step to execute. Marks plan complete if none left."""
        if self.execution is None:
            return None
        return self.execution.next_step()

    def build_instruction_for_step(self, step: PlanStepStatus) -> str:
        if self.execution is None:
            return ""
        return self.execution.build_step_instruction(step)

    def record_done(self, step_id: int, ok: bool) -> None:
        if self.execution:
            self.execution.mark_done(step_id, ok)

    def record_skip(self, step_id: int, reason: str = "") -> None:
        if self.execution:
            self.execution.mark_skipped(step_id, reason)

    def can_finalize(self) -> bool:
        """True if no plan, or all steps are done/skipped."""
        return self.plan_complete

    def finalize_summary(self) -> str:
        if self.execution:
            return self.execution.build_completion_message()
        return "Task completed."

    def progress_str(self) -> str:
        if self.execution:
            return self.execution.progress_str()
        return ""


def build_planner_prompt(
    prompt: str,
    system_context: str = "",
    history: str = "",
    lang: str = "en",
) -> str:
    example = """<plan>
<summary>Create 3 landing page files</summary>
<step>
<description>Create index.html with hero and CTA</description>
<detail>Write semantic HTML5 structure</detail>
</step>
<step>
<description>Create style.css with dark theme</description>
<detail>Add reset, typography, responsive grid</detail>
</step>
<step>
<description>Create script.js with interactions</description>
<detail>Mobile nav toggle, smooth scroll</detail>
</step>
</plan>"""
    if lang == "es":
        return f"""IMPORTANTE: Solo responde con XML. Nunca expliques, nunca añadas texto extra.

Ejemplo concreto para "crear landing page":
{example}

Ahora crea el plan para esta tarea. Mismo formato XML exacto.

CONTEXTO: {system_context}
TAREA: {prompt}"""
    return f"""CRITICAL: Respond ONLY with XML. Never explain, never add extra text.

Concrete example for "create landing page":
{example}

Now create the plan for this task. Same exact XML format.

CONTEXT: {system_context}
TASK: {prompt}"""


# Import for type hint (avoid circular import with ide.py)
from dataclasses import dataclass as _dc
try:
    from .ide import AgentPlan
except ImportError:
    @dataclass
    class AgentPlan:
        prompt: str = ""
        steps: list = field(default_factory=list)
        summary: str = ""
        active_step: int = 0
