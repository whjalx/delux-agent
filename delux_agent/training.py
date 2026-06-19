from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .agent import AgentRunResult, AgentStep


TRAINING_DIR_NAME = "training"
DATASET_FILE = "dataset.jsonl"
SYSTEM_TEMPLATE = """You are Delux, an AI assistant for system administration, file management, automation, and software development.

Capabilities:
- Run shell commands via sh/bash
- Read, write, append, and search files
- Execute and create reusable skills
- Remember facts across sessions

Rules:
- Never use sudo or privilege escalation
- Work autonomously. Return ONLY a JSON action object.

After each action you receive a result:
- If result starts with "SUCCESS:": the action succeeded. Do NOT repeat it. Proceed to the NEXT step or finalize.
- If result starts with "ERROR:": analyze the error and try a DIFFERENT approach. NEVER repeat the same failing command.

Allowed actions (return exactly one JSON object):
{"action":"shell","command":"command","timeout":60}
{"action":"read_file","path":"relative/path"}
{"action":"write_file","path":"relative/path","content":"..."}
{"action":"append_file","path":"relative/path","content":"..."}
{"action":"move_file","src":"path","dst":"path"}
{"action":"search_files","query":"text"}
{"action":"run_skill","skill":"skill-slug","args":"args","timeout":30}
{"action":"create_skill","name":"name","summary":"...","body":"..."}
{"action":"remember","note":"..."}
{"action":"final","message":"..."}
"""


@dataclass
class DatasetStats:
    total: int = 0
    steps_total: int = 0
    avg_steps: float = 0.0
    categories: dict[str, int] = None
    last_updated: str = ""
    file_size: str = ""


def ensure_training_dir(root: Path) -> Path:
    d = root / TRAINING_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_dataset_path(root: Path) -> Path:
    return ensure_training_dir(root) / DATASET_FILE


def count_dataset_lines(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def estimate_file_size(path: Path) -> str:
    if not path.exists():
        return "0 B"
    size = path.stat().st_size
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _categorize(steps: list[AgentStep]) -> list[str]:
    """Extract category tags from steps."""
    cats = set()
    for step in steps:
        action = step.action.get("action", "")
        if action == "shell":
            cmd = step.action.get("command", "").lower()
            if any(pkg in cmd for pkg in ("dnf", "apt", "pacman", "brew", "pip", "npm", "cargo")):
                cats.add("package_install")
            elif any(svc in cmd for svc in ("systemctl", "service", "enable")):
                cats.add("service_management")
            elif any(net in cmd for net in ("curl", "wget", "ping", "ss", "ip")):
                cats.add("networking")
            elif "git" in cmd:
                cats.add("git")
            elif any(f in cmd for f in ("chmod", "chown", "mkdir", "mv", "cp", "ln")):
                cats.add("file_operations")
            else:
                cats.add("shell_command")
        elif action in ("read_file", "write_file", "append_file", "move_file"):
            cats.add("file_operations")
        elif action == "search_files":
            cats.add("file_search")
        elif action in ("run_skill", "create_skill"):
            cats.add("skill_usage")
        elif action == "remember":
            cats.add("memory")
    return sorted(cats) if cats else ["general"]


def build_training_example(
    user_prompt: str,
    steps: list[AgentStep],
    final_answer: str,
    model_name: str = "",
) -> dict:
    """Build an OpenAI-compatible fine-tuning example from a successful run."""
    messages = [{"role": "system", "content": SYSTEM_TEMPLATE}]

    # Add user prompt
    messages.append({"role": "user", "content": user_prompt})

    # Add conversation turns
    for step in steps:
        action_json = json.dumps(step.action, ensure_ascii=False)
        messages.append({"role": "assistant", "content": action_json})

        if step.action.get("action") != "final":
            messages.append({"role": "user", "content": step.result})

    # Add final answer
    if steps and steps[-1].action.get("action") == "final":
        pass  # Already included in steps
    else:
        messages.append({
            "role": "assistant",
            "content": json.dumps({"action": "final", "message": final_answer}, ensure_ascii=False),
        })

    # Add metadata
    categories = _categorize(steps)

    example = {
        "messages": messages,
        "metadata": {
            "categories": categories,
            "num_steps": len(steps),
            "model": model_name,
            "timestamp": datetime.now().isoformat(),
        },
    }

    return example


def save_example(root: Path, example: dict) -> bool:
    """Append a training example to the dataset and update the self-learned cache."""
    path = get_dataset_path(root)
    learned_path = root / TRAINING_DIR_NAME / "self_learned_experts.json"
    
    try:
        # 1. Guardar en el dataset.jsonl (para fine-tuning)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(example, ensure_ascii=False) + "\n")
        
        # 2. Guardar en el cache de expertos (para aprendizaje en caliente)
        # Extraemos el primer mensaje del usuario y la respuesta final del asistente
        messages = example.get("messages", [])
        if len(messages) >= 2:
            user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
            # Buscamos la última respuesta del asistente que no sea un error
            assistant_msg = next((m["content"] for m in reversed(messages) if m["role"] == "assistant"), "")

            if user_msg and assistant_msg:
                learned_data = []
                if learned_path.exists():
                    try:
                        with open(learned_path, "r", encoding="utf-8") as f:
                            learned_data = json.load(f)
                    except:
                        learned_data = []

                new_expert = {
                    "user": user_msg,
                    "assistant": assistant_msg
                }
                
                # Insertar al principio y limitar a 700
                learned_data.insert(0, new_expert)
                learned_data = learned_data[:700]

                with open(learned_path, "w", encoding="utf-8") as f:
                    json.dump(learned_data, f, indent=2, ensure_ascii=False)
                    
        return True
    except Exception:
        return False


def get_stats(root: Path) -> DatasetStats:
    """Get dataset statistics."""
    path = get_dataset_path(root)
    stats = DatasetStats()
    stats.file_size = estimate_file_size(path)
    stats.total = count_dataset_lines(path)

    if stats.total == 0:
        return stats

    # Read and aggregate
    cats: dict[str, int] = {}
    total_steps = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                meta = data.get("metadata", {})
                total_steps += meta.get("num_steps", 0)
                for cat in meta.get("categories", []):
                    cats[cat] = cats.get(cat, 0) + 1
            except json.JSONDecodeError:
                continue

    stats.steps_total = total_steps
    stats.avg_steps = total_steps / stats.total if stats.total > 0 else 0
    stats.categories = dict(sorted(cats.items(), key=lambda x: -x[1]))
    if path.exists():
        stats.last_updated = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")

    return stats


def clear_dataset(root: Path) -> int:
    """Clear the dataset and return count of removed entries."""
    path = get_dataset_path(root)
    count = count_dataset_lines(path)
    if path.exists():
        path.unlink()
    return count


def export_for_finetuning(root: Path, output_path: Path) -> int:
    """Export dataset in a format ready for fine-tuning (remove metadata, validate)."""
    path = get_dataset_path(root)
    if not path.exists():
        return 0

    exported = 0
    with open(path, "r", encoding="utf-8") as src:
        with open(output_path, "w", encoding="utf-8") as dst:
            for line in src:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    # Remove metadata for fine-tuning format
                    if "metadata" in data:
                        del data["metadata"]
                    # Validate structure
                    if "messages" not in data or not isinstance(data["messages"], list):
                        continue
                    dst.write(json.dumps(data, ensure_ascii=False) + "\n")
                    exported += 1
                except json.JSONDecodeError:
                    continue

    return exported
