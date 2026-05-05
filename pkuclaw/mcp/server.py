from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from pkuclaw.core import logging as log
from pkuclaw.core.app import CoreRuntime
from pkuclaw.mcp.handlers import DaemonMcpToolHandler


@dataclass
class DaemonMcpServer:
    """HTTP JSON-RPC/MCP protocol layer for Agent -> CoreRuntime tools."""

    host: str
    port: int
    core_runtime: CoreRuntime
    default_channel: str = "feishu"

    def serve_forever(self) -> None:
        tool_handler = DaemonMcpToolHandler(
            core_runtime=self.core_runtime,
            default_channel=self.default_channel,
        )
        handler = _handler_factory(tool_handler)
        server = ThreadingHTTPServer((self.host, self.port), handler)
        log.ok(f"Daemon MCP listening: http://{self.host}:{self.port}")
        server.serve_forever()


def handle_mcp_request(
    tool_handler: DaemonMcpToolHandler,
    request: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    """Handle one HTTP JSON-RPC MCP request for tests and the HTTP adapter."""

    method = request.get("method")
    request_id = request.get("id")
    try:
        if method == "initialize":
            return _mcp_result(
                request_id,
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "pkuclaw-daemon",
                        "version": "0.1.0",
                    },
                },
            )
        if method == "notifications/initialized":
            return 202, {}
        if method == "tools/list":
            return _mcp_result(request_id, {"tools": tool_handler.list_tools()})
        if method == "tools/call":
            params = request.get("params")
            if not isinstance(params, dict):
                raise RuntimeError("params must be an object")
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str) or not name.strip():
                raise RuntimeError("tool name is required")
            if not isinstance(arguments, dict):
                raise RuntimeError("tool arguments must be an object")
            result = tool_handler.call_tool(name.strip(), arguments)
            return _mcp_result(
                request_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                asdict(result),
                                ensure_ascii=False,
                            ),
                        }
                    ],
                    "isError": not result.ok,
                },
            )
        raise RuntimeError(f"unsupported MCP method: {method}")
    except Exception as exc:
        return _mcp_error(request_id, str(exc))


def _handler_factory(
    tool_handler: DaemonMcpToolHandler,
) -> type[BaseHTTPRequestHandler]:
    class DaemonMcpHttpHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib API
            if self.path != "/health":
                self._write_json(404, {"ok": False, "message": "not found"})
                return
            self._write_json(200, {"ok": True, "message": "ok"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib API
            if self.path != "/mcp":
                self._write_json(404, {"ok": False, "message": "not found"})
                return
            try:
                status, payload = handle_mcp_request(
                    tool_handler,
                    self._read_payload(),
                )
            except Exception as exc:
                status, payload = _mcp_error(None, str(exc))
            self._write_json(status, payload)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_payload(self) -> dict[str, Any]:
            length = int(self.headers.get("content-length", "0") or "0")
            raw = self.rfile.read(length).decode("utf-8")
            data = json.loads(raw or "{}")
            if not isinstance(data, dict):
                raise RuntimeError("payload must be a JSON object")
            return data

        def _write_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return DaemonMcpHttpHandler


def _mcp_result(request_id: Any, result: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return 200, {"jsonrpc": "2.0", "id": request_id, "result": result}


def _mcp_error(request_id: Any, message: str) -> tuple[int, dict[str, Any]]:
    return (
        200,
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32603, "message": message},
        },
    )
