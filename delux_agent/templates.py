from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ParsedAction:
    action: str
    params: dict[str, Any]
    raw: dict[str, Any]


PARSE_STRATEGIES = [
    "direct_json",
    "markdown_json",
    "regex_json",
    "no_action_wrap",
    "plain_text",
]


def _try_direct_json(text: str) -> dict | None:
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    return None


def _try_markdown_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return None


def _try_regex_json(text: str) -> dict | None:
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            obj = json.loads(match.group())
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return None


def _try_no_action_wrap(obj: dict) -> ParsedAction | None:
    if "action" not in obj:
        msg = obj.get("message") or obj.get("response") or obj.get("answer") or json.dumps(obj, ensure_ascii=False)[:200]
        return ParsedAction(action="final", params={"message": str(msg)}, raw={"action": "final", "message": str(msg)})
    return None


def parse_action(text: str, preferred_strategy: str | None = None) -> tuple[ParsedAction, str]:
    strategies = list(PARSE_STRATEGIES)
    if preferred_strategy and preferred_strategy in strategies:
        strategies.remove(preferred_strategy)
        strategies.insert(0, preferred_strategy)

    last_error = ""
    for strategy in strategies:
        obj = None
        if strategy == "direct_json":
            obj = _try_direct_json(text)
        elif strategy == "markdown_json":
            obj = _try_markdown_json(text)
        elif strategy == "regex_json":
            obj = _try_regex_json(text)

        if obj is not None:
            wrapped = _try_no_action_wrap(obj)
            if wrapped:
                return wrapped, strategy
            action = obj.get("action", "final")
            params = {k: v for k, v in obj.items() if k != "action"}
            return ParsedAction(action=action, params=params, raw=obj), strategy

    return ParsedAction(
        action="final",
        params={"message": text.strip(), "_plain_text": True},
        raw={"action": "final", "message": text.strip(), "_plain_text": True},
    ), "plain_text"


@dataclass
class ModelTemplate:
    name: str
    preferred_strategy: str = "auto"
    system_suffix: str = ""


TEMPLATE_FILE = "templates.json"


def _load_templates_file(root: Path) -> dict[str, dict]:
    path = root / TEMPLATE_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_templates_file(root: Path, templates: dict) -> None:
    path = root / TEMPLATE_FILE
    path.write_text(json.dumps(templates, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get_model_template(model_name: str, root: Path) -> ModelTemplate:
    templates = _load_templates_file(root)
    if model_name in templates:
        t = templates[model_name]
        return ModelTemplate(
            name=model_name,
            preferred_strategy=t.get("preferred_strategy", "auto"),
            system_suffix=t.get("system_suffix", ""),
        )
    return ModelTemplate(name=model_name)


def record_successful_strategy(model_name: str, strategy: str, root: Path) -> None:
    templates = _load_templates_file(root)
    if model_name not in templates:
        templates[model_name] = {"preferred_strategy": strategy, "system_suffix": ""}
    else:
        templates[model_name]["preferred_strategy"] = strategy
    _save_templates_file(root, templates)


def list_templates(root: Path) -> list[tuple[str, ModelTemplate]]:
    templates = _load_templates_file(root)
    result = []
    for name, t in templates.items():
        result.append((name, ModelTemplate(
            name=name,
            preferred_strategy=t.get("preferred_strategy", "auto"),
            system_suffix=t.get("system_suffix", ""),
        )))
    return result


def set_template(model_name: str, strategy: str | None = None, suffix: str | None = None, root: Path = None) -> None:
    templates = _load_templates_file(root)
    if model_name not in templates:
        templates[model_name] = {"preferred_strategy": "auto", "system_suffix": ""}
    if strategy is not None:
        if strategy == "reset":
            templates[model_name]["preferred_strategy"] = "auto"
        else:
            templates[model_name]["preferred_strategy"] = strategy
    if suffix is not None:
        templates[model_name]["system_suffix"] = suffix
    _save_templates_file(root, templates)


def get_action_format_instructions(model_name: str, root: Path) -> str:
    t = get_model_template(model_name, root)
    if t.system_suffix:
        return t.system_suffix
    base = (
        "\nAllowed actions:\n"
        '{"action":"shell","command":"fish command","timeout":60}\n'
        '{"action":"read_file","path":"relative/path"}\n'
        '{"action":"write_file","path":"relative/path","content":"..."}\n'
        '{"action":"append_file","path":"relative/path","content":"..."}\n'
        '{"action":"search_files","query":"text"}\n'
        '{"action":"run_skill","skill":"skill-slug","args":"arg1 arg2 ...","timeout":30}\n'
        '{"action":"create_skill","name":"name","summary":"...","body":"..."}\n'
        '{"action":"call_mcp","server":"server-name","tool":"tool-name","arguments":{...}}\n'
        '{"action":"remember","note":"..."}\n'
        '{"action":"browser_navigate","url":"https://example.com"}\n'
        '{"action":"browser_click","selector":"a.link"}\n'
        '{"action":"browser_type","selector":"input","text":"query"}\n'
        '{"action":"browser_scroll","direction":"down","amount":500}\n'
        '{"action":"browser_snapshot"}\n'
        '{"action":"browser_screenshot"}\n'
        '{"action":"browser_extract"}\n'
        '{"action":"browser_back"}\n'
        '{"action":"browser_close"}\n'
        '{"action":"vision_analyze","image_path":"/path/to/img.png","prompt":"describe"}\n'
        '{"action":"delegate_task","task":"sub-task","max_steps":12,"timeout":120}\n'
        '{"action":"cron_add","name":"job","expression":"0 * * * *","command":"cmd"}\n'
        '{"action":"cron_remove","job_id":1}\n'
        '{"action":"cron_list"}\n'
        '{"action":"cron_run","job_id":1}\n'
        '{"action":"kanban_add","title":"task","description":"desc"}\n'
        '{"action":"kanban_list"}\n'
        '{"action":"kanban_move","card_id":1,"status":"done"}\n'
        '{"action":"kanban_show","card_id":1}\n'
        '{"action":"kanban_delete","card_id":1}\n'
        '{"action":"computer_screenshot"}\n'
        '{"action":"computer_click","x":100,"y":200}\n'
        '{"action":"computer_type","text":"hello"}\n'
        '{"action":"computer_keypress","key":"Return"}\n'
        '{"action":"final","message":"..."}\n'
    )
    return base
