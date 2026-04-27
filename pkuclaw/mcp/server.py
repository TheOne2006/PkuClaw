from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from pkuclaw.core import logging as log
from pkuclaw.mcp.channel_tools import ChannelToolBackend, ChannelToolResult


@dataclass
class ChannelToolServer:
    host: str
    port: int
    backend: ChannelToolBackend

    def serve_forever(self) -> None:
        handler = _handler_factory(self.backend)
        server = ThreadingHTTPServer((self.host, self.port), handler)
        log.ok(f"Channel MCP tool server listening: http://{self.host}:{self.port}")
        server.serve_forever()


def _handler_factory(backend: ChannelToolBackend) -> type[BaseHTTPRequestHandler]:
    class ChannelToolHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib API
            if self.path != "/health":
                self._write_json(404, {"ok": False, "message": "not found"})
                return
            self._write_json(200, {"ok": True, "message": "ok"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib API
            if self.path == "/mcp":
                self._handle_mcp()
                return
            tool_name = self.path.removeprefix("/tools/").strip("/")
            tools: dict[str, Callable[[dict[str, Any]], ChannelToolResult]] = {
                "channel_send_text": _call_send_text,
                "channel_send_card": _call_send_card,
                "channel_send_image": _call_send_image,
                "channel_update_card": _call_update_card,
            }
            handler = tools.get(tool_name)
            if handler is None:
                self._write_json(404, {"ok": False, "message": "unknown tool"})
                return
            try:
                payload = self._read_payload()
                result = handler(payload)
            except Exception as exc:
                self._write_json(400, {"ok": False, "message": str(exc)})
                return
            self._write_json(200 if result.ok else 400, asdict(result))

        def _handle_mcp(self) -> None:
            request = self._read_payload()
            method = request.get("method")
            request_id = request.get("id")
            try:
                if method == "initialize":
                    self._write_mcp_result(
                        request_id,
                        {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {"tools": {}},
                            "serverInfo": {
                                "name": "pkuclaw-channel-tools",
                                "version": "0.1.0",
                            },
                        },
                    )
                    return
                if method == "notifications/initialized":
                    self._write_json(202, {})
                    return
                if method == "tools/list":
                    self._write_mcp_result(request_id, {"tools": _mcp_tools()})
                    return
                if method == "tools/call":
                    params = request.get("params")
                    if not isinstance(params, dict):
                        raise RuntimeError("params must be an object")
                    name = params.get("name")
                    arguments = params.get("arguments", {})
                    if not isinstance(name, str):
                        raise RuntimeError("tool name is required")
                    if not isinstance(arguments, dict):
                        raise RuntimeError("tool arguments must be an object")
                    result = self._call_tool(name, arguments)
                    self._write_mcp_result(
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
                    return
                raise RuntimeError(f"unsupported MCP method: {method}")
            except Exception as exc:
                self._write_mcp_error(request_id, str(exc))

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

        def _write_mcp_result(self, request_id: Any, result: dict[str, Any]) -> None:
            self._write_json(
                200,
                {"jsonrpc": "2.0", "id": request_id, "result": result},
            )

        def _write_mcp_error(self, request_id: Any, message: str) -> None:
            self._write_json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32603, "message": message},
                },
            )

        def _call_tool(self, name: str, arguments: dict[str, Any]) -> ChannelToolResult:
            tools: dict[str, Callable[[dict[str, Any]], ChannelToolResult]] = {
                "channel_send_text": _call_send_text,
                "channel_send_card": _call_send_card,
                "channel_send_image": _call_send_image,
                "channel_update_card": _call_update_card,
            }
            handler = tools.get(name)
            if handler is None:
                raise RuntimeError(f"unknown tool: {name}")
            return handler(arguments)

    def _call_send_text(payload: dict[str, Any]) -> ChannelToolResult:
        return backend.channel_send_text(
            target_id=_required_str(payload, "target_id"),
            text=_required_str(payload, "text"),
            target_type=_optional_str(payload, "target_type") or "chat_id",
        )

    def _call_send_card(payload: dict[str, Any]) -> ChannelToolResult:
        card = payload.get("card")
        if not isinstance(card, dict):
            raise RuntimeError("card must be an object")
        return backend.channel_send_card(
            target_id=_required_str(payload, "target_id"),
            card=card,
            target_type=_optional_str(payload, "target_type") or "chat_id",
        )

    def _call_send_image(payload: dict[str, Any]) -> ChannelToolResult:
        return backend.channel_send_image(
            target_id=_required_str(payload, "target_id"),
            image_path=_required_str(payload, "image_path"),
            target_type=_optional_str(payload, "target_type") or "chat_id",
        )

    def _call_update_card(payload: dict[str, Any]) -> ChannelToolResult:
        card = payload.get("card")
        sequence = payload.get("sequence")
        if not isinstance(card, dict):
            raise RuntimeError("card must be an object")
        if not isinstance(sequence, int):
            raise RuntimeError("sequence must be an integer")
        return backend.channel_update_card(
            card_id=_required_str(payload, "card_id"),
            card=card,
            sequence=sequence,
        )

    return ChannelToolHandler


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{key} is required")
    return value.strip()


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"{key} must be a string")
    value = value.strip()
    return value or None


def _mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "channel_send_text",
            "description": "Send a text notification through the active channel backend.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "string"},
                    "target_type": {"type": "string", "default": "chat_id"},
                    "text": {"type": "string"},
                },
                "required": ["target_id", "text"],
            },
        },
        {
            "name": "channel_send_card",
            "description": "Send a structured card through the active channel backend.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "string"},
                    "target_type": {"type": "string", "default": "chat_id"},
                    "card": {"type": "object"},
                },
                "required": ["target_id", "card"],
            },
        },
        {
            "name": "channel_send_image",
            "description": "Send an image through the active channel backend.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "string"},
                    "target_type": {"type": "string", "default": "chat_id"},
                    "image_path": {"type": "string"},
                },
                "required": ["target_id", "image_path"],
            },
        },
        {
            "name": "channel_update_card",
            "description": "Update a previously sent card.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "card_id": {"type": "string"},
                    "card": {"type": "object"},
                    "sequence": {"type": "integer"},
                },
                "required": ["card_id", "card", "sequence"],
            },
        },
    ]
