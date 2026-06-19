from __future__ import annotations

import json
import tempfile
from pathlib import Path

from delux_agent.agent import AgentRunResult, AgentStep
from delux_agent.training import (
    build_training_example,
    clear_dataset,
    export_for_finetuning,
    get_dataset_path,
    get_stats,
    save_example,
)


def _make_step(num: int, action: dict, result: str) -> AgentStep:
    return AgentStep(number=num, action=action, result=result)


def _make_result(steps: list[AgentStep], answer: str = "done") -> AgentRunResult:
    return AgentRunResult(answer=answer, steps=steps, transcript=[])


def test_build_training_example_basic():
    steps = [
        _make_step(1, {"action": "shell", "command": "echo hello"}, "SUCCESS: hello"),
        _make_step(2, {"action": "final", "message": "done"}, "Final answer emitted."),
    ]
    result = _make_result(steps, answer="done")
    example = build_training_example("echo hello", result.steps, result.answer, "test-model")

    assert "messages" in example
    assert "metadata" in example
    assert len(example["messages"]) >= 3

    msg = example["messages"]
    assert msg[0]["role"] == "system"
    assert msg[1]["role"] == "user"
    assert msg[1]["content"] == "echo hello"

    meta = example["metadata"]
    assert meta["model"] == "test-model"
    assert meta["num_steps"] == 2
    assert "categories" in meta
    assert "timestamp" in meta


def test_build_training_example_multistep():
    steps = [
        _make_step(1, {"action": "shell", "command": "mkdir test"}, "SUCCESS: "),
        _make_step(2, {"action": "write_file", "path": "test/file.txt", "content": "hi"}, "SUCCESS: written"),
        _make_step(3, {"action": "final", "message": "created"}, "Final answer emitted."),
    ]
    result = _make_result(steps, answer="created")
    example = build_training_example("create file", result.steps, result.answer)

    messages = example["messages"]
    assistant_count = sum(1 for m in messages if m["role"] == "assistant")
    user_count = sum(1 for m in messages if m["role"] == "user")

    assert assistant_count == 3
    assert user_count == 3


def test_build_training_example_no_final_step():
    steps = [
        _make_step(1, {"action": "shell", "command": "date"}, "SUCCESS: 2024-01-01"),
    ]
    result = _make_result(steps, answer="The date is 2024-01-01")
    example = build_training_example("what date?", result.steps, result.answer)

    messages = example["messages"]
    last_msg = messages[-1]
    assert last_msg["role"] == "assistant"
    assert "final" in last_msg["content"]
    assert "The date is 2024-01-01" in last_msg["content"]


def test_build_training_example_categorization():
    steps = [
        _make_step(1, {"action": "shell", "command": "dnf install nginx"}, "SUCCESS: installed"),
        _make_step(2, {"action": "final", "message": "ok"}, "Final answer emitted."),
    ]
    result = _make_result(steps, answer="ok")
    example = build_training_example("install nginx", result.steps, result.answer)

    assert "package_install" in example["metadata"]["categories"]


def test_save_and_read_dataset():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        example = build_training_example("test", [
            _make_step(1, {"action": "shell", "command": "echo test"}, "SUCCESS: test"),
        ], "ok")

        assert save_example(root, example)
        path = get_dataset_path(root)
        assert path.exists()

        stats = get_stats(root)
        assert stats.total == 1
        assert stats.steps_total == 1

        line = path.read_text().strip()
        parsed = json.loads(line)
        assert "messages" in parsed
        assert "metadata" in parsed


def test_export_for_finetuning_strips_metadata():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        example = build_training_example("test", [
            _make_step(1, {"action": "shell", "command": "echo test"}, "SUCCESS: test"),
            _make_step(2, {"action": "final", "message": "done"}, "Final answer emitted."),
        ], "done")

        save_example(root, example)
        export_path = Path(td) / "export.jsonl"
        count = export_for_finetuning(root, export_path)

        assert count == 1
        assert export_path.exists()

        exported = json.loads(export_path.read_text().strip())
        assert "metadata" not in exported
        assert "messages" in exported

        msgs = exported["messages"]
        assert msgs[0]["role"] == "system"
        assert any(m["role"] == "user" for m in msgs)
        assert any(m["role"] == "assistant" for m in msgs)


def test_export_for_finetuning_multi_example():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i in range(3):
            example = build_training_example(f"task {i}", [
                _make_step(1, {"action": "shell", "command": f"echo {i}"}, "SUCCESS: ok"),
                _make_step(2, {"action": "final", "message": f"done {i}"}, "Final answer emitted."),
            ], f"done {i}")
            save_example(root, example)

        export_path = Path(td) / "export.jsonl"
        count = export_for_finetuning(root, export_path)

        assert count == 3

        lines = export_path.read_text().strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            data = json.loads(line)
            assert "metadata" not in data
            assert "messages" in data


def test_export_handles_invalid_lines():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        path = get_dataset_path(root)

        path.write_text("not valid json\n", encoding="utf-8")

        example = build_training_example("test", [
            _make_step(1, {"action": "final", "message": "ok"}, "Final answer emitted."),
        ], "ok")
        save_example(root, example)

        export_path = Path(td) / "export.jsonl"
        count = export_for_finetuning(root, export_path)

        assert count == 1

        lines = export_path.read_text().strip().split("\n")
        assert len(lines) == 1


def test_clear_dataset():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        example = build_training_example("test", [
            _make_step(1, {"action": "final", "message": "ok"}, "Final answer emitted."),
        ], "ok")
        save_example(root, example)
        save_example(root, example)

        stats = get_stats(root)
        assert stats.total == 2

        removed = clear_dataset(root)
        assert removed == 2

        stats = get_stats(root)
        assert stats.total == 0


def test_dataset_stats_aggregation():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        for i in range(4):
            example = build_training_example(f"task {i}", [
                _make_step(1, {"action": "shell", "command": "git status"}, "SUCCESS: ok"),
                _make_step(2, {"action": "final", "message": "ok"}, "Final answer emitted."),
            ], "ok")
            save_example(root, example)

        for i in range(2):
            example = build_training_example(f"file task {i}", [
                _make_step(1, {"action": "write_file", "path": "f.txt", "content": "x"}, "SUCCESS: ok"),
                _make_step(2, {"action": "final", "message": "ok"}, "Final answer emitted."),
            ], "ok")
            save_example(root, example)

        stats = get_stats(root)
        assert stats.total == 6
        assert stats.steps_total == 12
        assert stats.avg_steps == 2.0
        assert "git" in stats.categories
        assert "file_operations" in stats.categories
