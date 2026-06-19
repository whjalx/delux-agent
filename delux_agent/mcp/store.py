from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .client import MCPClient, MCPTool, MCPResource


MCP_SERVERS_FILE = "mcp_servers.json"
MCP_TOOLS_CACHE = "mcp_tools.json"


@dataclass
class MCPServerEntry:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict = field(default_factory=dict)
    description: str = ""
    enabled: bool = True


def _load_servers(root: Path) -> dict[str, dict]:
    path = root / MCP_SERVERS_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_servers(root: Path, servers: dict) -> None:
    path = root / MCP_SERVERS_FILE
    path.write_text(json.dumps(servers, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_mcp_servers(root: Path) -> list[MCPServerEntry]:
    servers = _load_servers(root)
    result = []
    for name, s in servers.items():
        result.append(MCPServerEntry(
            name=name,
            command=s.get("command", ""),
            args=s.get("args", []),
            env=s.get("env", {}),
            description=s.get("description", ""),
            enabled=s.get("enabled", True),
        ))
    return result


def add_mcp_server(root: Path, entry: MCPServerEntry) -> None:
    servers = _load_servers(root)
    servers[entry.name] = {
        "command": entry.command,
        "args": entry.args,
        "env": entry.env,
        "description": entry.description,
        "enabled": entry.enabled,
    }
    _save_servers(root, servers)


def remove_mcp_server(root: Path, name: str) -> bool:
    servers = _load_servers(root)
    if name in servers:
        del servers[name]
        _save_servers(root, servers)
        return True
    return False


def toggle_mcp_server(root: Path, name: str) -> bool:
    servers = _load_servers(root)
    if name in servers:
        servers[name]["enabled"] = not servers[name].get("enabled", True)
        _save_servers(root, servers)
        return True
    return False


def get_enabled_servers(root: Path) -> list[MCPServerEntry]:
    return [s for s in load_mcp_servers(root) if s.enabled]


def discover_tools(root: Path, server_name: str | None = None) -> dict[str, list[MCPTool]]:
    servers = get_enabled_servers(root)
    if server_name:
        servers = [s for s in servers if s.name == server_name]

    all_tools: dict[str, list[MCPTool]] = {}
    for s in servers:
        try:
            client = MCPClient(s.name, s.command, s.args, s.env or None)
            client.start()
            client.initialize()
            tools = client.list_tools()
            all_tools[s.name] = tools
            client.stop()
        except Exception as e:
            all_tools[s.name] = [MCPTool(name="error", description=f"Failed to connect: {e}")]
    return all_tools


def cache_tools(root: Path, tools: dict[str, list[MCPTool]]) -> None:
    path = root / MCP_TOOLS_CACHE
    cache = {}
    for server, tool_list in tools.items():
        cache[server] = [
            {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
            for t in tool_list
        ]
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_cached_tools(root: Path) -> dict[str, list[MCPTool]]:
    path = root / MCP_TOOLS_CACHE
    if not path.exists():
        return {}
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    result = {}
    for server, tool_list in cache.items():
        result[server] = [
            MCPTool(name=t["name"], description=t.get("description", ""), input_schema=t.get("inputSchema", {}))
            for t in tool_list
        ]
    return result


def get_tools_for_prompt(root: Path) -> str:
    cached = load_cached_tools(root)
    if not cached:
        return ""

    lines = ["\nMCP Server Tools:"]
    for server, tools in cached.items():
        lines.append(f"\nServer: {server}")
        for t in tools:
            if t.name == "error":
                lines.append(f"  (error: {t.description})")
            else:
                lines.append(f"  - {t.name}: {t.description}")
    lines.append("\nTo use an MCP tool: {\"action\":\"call_mcp\",\"server\":\"<server>\",\"tool\":\"<tool>\",\"arguments\":{...}}")
    return "\n".join(lines)
