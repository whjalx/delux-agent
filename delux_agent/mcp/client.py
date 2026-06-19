from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


MCP_PROTOCOL_VERSION = "2025-06-18"


@dataclass
class MCPTool:
    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)


@dataclass
class MCPResource:
    name: str
    uri: str = ""
    description: str = ""
    mime_type: str = ""


class MCPError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"MCP Error {code}: {message}")


class MCPClient:
    def __init__(self, name: str, command: str, args: list[str], env: dict | None = None, cwd: Path | None = None):
        self.name = name
        self.command = command
        self.args = args
        self._env = env
        self._cwd = cwd
        self._process: subprocess.Popen | None = None
        self._request_id = 0
        self._initialized = False

    def start(self) -> None:
        if self._process and self._process.poll() is None:
            return
        self._process = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=self._env,
            cwd=str(self._cwd) if self._cwd else None,
        )

    def stop(self) -> None:
        if self._process:
            try:
                self._send_notification("notifications/initialized")
            except Exception:
                pass
            try:
                self._process.stdin.close()
            except Exception:
                pass
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
            self._initialized = False

    def initialize(self) -> dict:
        self.start()
        result = self._send_request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "delux", "version": "1.0.0"},
        })
        self._send_notification("notifications/initialized")
        self._initialized = True
        return result

    def list_tools(self) -> list[MCPTool]:
        result = self._send_request("tools/list")
        tools = []
        for t in result.get("tools", []):
            tools.append(MCPTool(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            ))
        return tools

    def list_resources(self) -> list[MCPResource]:
        try:
            result = self._send_request("resources/list")
            resources = []
            for r in result.get("resources", []):
                resources.append(MCPResource(
                    name=r["name"],
                    uri=r.get("uri", ""),
                    description=r.get("description", ""),
                    mime_type=r.get("mimeType", ""),
                ))
            return resources
        except MCPError:
            return []

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        parts = []
        for content in result.get("content", []):
            if content.get("type") == "text":
                parts.append(content["text"])
            elif content.get("type") == "image":
                parts.append(f"[image:{content.get('mimeType', 'unknown')}]")
            elif content.get("type") == "resource":
                res = content.get("resource", {})
                parts.append(f"[resource:{res.get('uri', 'unknown')}]")
        if result.get("isError"):
            return "ERROR: " + "\n".join(parts) if parts else "ERROR: Tool returned error"
        return "\n".join(parts) if parts else "SUCCESS: Tool executed successfully"

    def read_resource(self, uri: str) -> str:
        result = self._send_request("resources/read", {"uri": uri})
        parts = []
        for content in result.get("contents", []):
            if content.get("type") == "text":
                parts.append(content["text"])
            elif content.get("type") == "blob":
                parts.append(f"[blob:{content.get('mimeType', 'unknown')}]")
        return "\n".join(parts)

    def _send_request(self, method: str, params: dict | None = None) -> dict:
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params:
            request["params"] = params
        self._send_json(request)
        return self._read_response(self._request_id)

    def _send_notification(self, method: str, params: dict | None = None) -> None:
        request = {"jsonrpc": "2.0", "method": method}
        if params:
            request["params"] = params
        self._send_json(request)

    def _send_json(self, data: dict) -> None:
        if not self._process or self._process.poll() is not None:
            raise MCPError(-32603, "Server process not running")
        line = json.dumps(data, ensure_ascii=False) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()

    def _read_response(self, request_id: int) -> dict:
        while True:
            line = self._process.stdout.readline()
            if not line:
                raise MCPError(-32000, "Server disconnected")
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("jsonrpc") != "2.0":
                continue
            if "id" in data and data["id"] == request_id:
                if "error" in data:
                    err = data["error"]
                    raise MCPError(err.get("code", -1), err.get("message", "Unknown error"))
                return data.get("result", {})
            # Ignore notifications and other responses

    def __enter__(self):
        self.start()
        self.initialize()
        return self

    def __exit__(self, *args):
        self.stop()

    def __del__(self):
        self.stop()
