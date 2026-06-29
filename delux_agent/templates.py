from __future__ import annotations

import html
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
    "xml_action",
    "direct_json",
    "markdown_json",
    "regex_json",
    "no_action_wrap",
    "plain_text",
]


def action_to_xml(action: dict) -> str:
    """Convert an action dict to XML tag format.

    Input:  {"action":"shell","command":"ls -la","timeout":60}
    Output: <action>shell</action>
            <command>ls -la</command>
            <timeout>60</timeout>
    """
    lines = []
    if "action" in action:
        lines.append(f"<action>{html.escape(str(action['action']))}</action>")
    for key, value in action.items():
        if key == "action":
            continue
        if isinstance(value, (dict, list)):
            val = json.dumps(value, ensure_ascii=False)
            lines.append(f"<{key}>{html.escape(val)}</{key}>")
        elif isinstance(value, bool):
            lines.append(f"<{key}>{str(value).lower()}</{key}>")
        else:
            lines.append(f"<{key}>{html.escape(str(value))}</{key}>")
    return "\n".join(lines)


def _try_xml_action(text: str) -> dict | None:
    """Parse <action>...</action> and param tags from model output.

    Handles:
      <action>shell</action>
      <command>ls -la</command>

    Also handles JSON-inside-tags for complex values:
      <arguments>{"key": "value"}</arguments>

    Very tolerant of extra text, whitespace, and HTML entities.
    """
    text = text.strip()
    m = re.search(r"<action>\s*(.*?)\s*</action>", text, re.DOTALL)
    if not m:
        return None
    action_name = m.group(1).strip()
    if not action_name:
        return None
    result = {"action": action_name}

    for m in re.finditer(r"<(\w+)>([\s\S]*?)</\1>", text):
        tag = m.group(1)
        if tag == "action":
            continue
        raw = m.group(2).strip()
        val: Any = html.unescape(raw)
        # Try number
        try:
            if "." in val:
                val = float(val)
            else:
                val = int(val)
        except (ValueError, TypeError):
            if val.lower() == "true":
                val = True
            elif val.lower() == "false":
                val = False
            elif val.startswith("{") or val.startswith("["):
                try:
                    val = json.loads(val)
                except json.JSONDecodeError:
                    pass
        result[tag] = val
    return result


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

    for strategy in strategies:
        obj = None
        if strategy == "xml_action":
            obj = _try_xml_action(text)
        elif strategy == "direct_json":
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
        "\nAllowed actions (XML format):\n"
        "<action>shell</action>\n<command>command</command>\n<timeout>60</timeout>\n"
        "<action>read_file</action>\n<path>relative/path</path>\n"
        "<action>write_file</action>\n<path>relative/path</path>\n<content>...</content>\n"
        "<action>append_file</action>\n<path>relative/path</path>\n<content>...</content>\n"
        "<action>search_files</action>\n<query>text</query>\n"
        "<action>run_skill</action>\n<skill>skill-slug</skill>\n<args>arg1 arg2 ...</args>\n<timeout>30</timeout>\n"
        "<action>create_skill</action>\n<name>name</name>\n<summary>...</summary>\n<body>...</body>\n"
        "<action>call_mcp</action>\n<server>server-name</server>\n<tool>tool-name</tool>\n<arguments>{\"key\": \"value\"}</arguments>\n"
        "<action>remember</action>\n<note>...</note>\n"
        "<action>browser_navigate</action>\n<url>https://example.com</url>\n"
        "<action>browser_click</action>\n<selector>a.link</selector>\n"
        "<action>browser_type</action>\n<selector>input</selector>\n<text>query</text>\n"
        "<action>browser_scroll</action>\n<direction>down</direction>\n<amount>500</amount>\n"
        "<action>browser_snapshot</action>\n"
        "<action>browser_screenshot</action>\n"
        "<action>browser_extract</action>\n"
        "<action>browser_back</action>\n"
        "<action>browser_close</action>\n"
        "<action>vision_analyze</action>\n<image_path>/path/to/img.png</image_path>\n<prompt>describe</prompt>\n"
        "<action>delegate_task</action>\n<task>sub-task</task>\n<max_steps>12</max_steps>\n<timeout>120</timeout>\n"
        "<action>cron_add</action>\n<name>job</name>\n<expression>0 * * * *</expression>\n<command>cmd</command>\n"
        "<action>cron_remove</action>\n<job_id>1</job_id>\n"
        "<action>cron_list</action>\n"
        "<action>cron_run</action>\n<job_id>1</job_id>\n"
        "<action>kanban_add</action>\n<title>task</title>\n<description>desc</description>\n"
        "<action>kanban_list</action>\n"
        "<action>kanban_move</action>\n<card_id>1</card_id>\n<status>done</status>\n"
        "<action>kanban_show</action>\n<card_id>1</card_id>\n"
        "<action>kanban_delete</action>\n<card_id>1</card_id>\n"
        "<action>computer_screenshot</action>\n"
        "<action>computer_click</action>\n<x>100</x>\n<y>200</y>\n"
        "<action>computer_type</action>\n<text>hello</text>\n"
        "<action>computer_keypress</action>\n<key>Return</key>\n"
        "<action>set_tasks</action>\n<tasks>[\"task 1\", \"task 2\"]</tasks>\n"
        "<action>task_done</action>\n<task>task 1</task>\n"
        "<action>final</action>\n<summary>What was requested vs what was done</summary>\n<message>...</message>\n"
    )
    return base
