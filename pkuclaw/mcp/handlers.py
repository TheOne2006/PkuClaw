from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pkuclaw.channels.base import ChannelOutboundResult
from pkuclaw.core.app import CoreRuntime
from pkuclaw.mcp.channel_tools import McpToolResult
from pkuclaw.mcp.schemas import list_tool_schemas


@dataclass
class DaemonMcpToolHandler:
    """Dispatch daemon MCP tool calls into CoreRuntime-owned capabilities."""

    core_runtime: CoreRuntime
    default_channel: str = "feishu"

    def list_tools(self) -> list[dict[str, Any]]:
        return list_tool_schemas()

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> McpToolResult:
        args = arguments or {}
        if not isinstance(args, dict):
            raise RuntimeError("tool arguments must be an object")
        dispatch: dict[str, Callable[[dict[str, Any]], McpToolResult]] = {
            "channel_send_text": self._channel_send_text,
            "channel_send_card": self._channel_send_card,
            "channel_send_image": self._channel_send_image,
            "channel_update_card": self._channel_update_card,
            "runtime_get_status": self._runtime_get_status,
            "runtime_get_config": self._runtime_get_config,
            "runtime_list_loops": self._runtime_list_loops,
            "runtime_list_recent_runs": self._runtime_list_recent_runs,
            "runtime_get_run": self._runtime_get_run,
            "runtime_add_loop": self._runtime_add_loop,
            "runtime_update_loop": self._runtime_update_loop,
            "runtime_enable_loop": self._runtime_enable_loop,
            "runtime_disable_loop": self._runtime_disable_loop,
        }
        handler = dispatch.get(name)
        if handler is None:
            raise RuntimeError(f"unknown tool: {name}")
        return handler(args)

    def _channel_send_text(self, args: dict[str, Any]) -> McpToolResult:
        return _as_tool_result(
            self.core_runtime.send_channel_text(
                channel=self._channel(args),
                target_type=_optional_str(args, "target_type") or "chat_id",
                target_id=_required_str(args, "target_id"),
                text=_required_str(args, "text"),
            )
        )

    def _channel_send_card(self, args: dict[str, Any]) -> McpToolResult:
        card = _required_object(args, "card")
        return _as_tool_result(
            self.core_runtime.send_channel_card(
                channel=self._channel(args),
                target_type=_optional_str(args, "target_type") or "chat_id",
                target_id=_required_str(args, "target_id"),
                card=card,
            )
        )

    def _channel_send_image(self, args: dict[str, Any]) -> McpToolResult:
        return _as_tool_result(
            self.core_runtime.send_channel_image(
                channel=self._channel(args),
                target_type=_optional_str(args, "target_type") or "chat_id",
                target_id=_required_str(args, "target_id"),
                image_path=_required_str(args, "image_path"),
            )
        )

    def _channel_update_card(self, args: dict[str, Any]) -> McpToolResult:
        sequence = args.get("sequence")
        if not isinstance(sequence, int):
            raise RuntimeError("sequence must be an integer")
        return _as_tool_result(
            self.core_runtime.update_channel_card(
                channel=self._channel(args),
                card_id=_required_str(args, "card_id"),
                card=_required_object(args, "card"),
                sequence=sequence,
            )
        )

    def _runtime_get_status(self, args: dict[str, Any]) -> McpToolResult:
        return McpToolResult(
            ok=True,
            message="runtime status",
            data=self.core_runtime.runtime_get_status(
                conversation_id=_optional_str(args, "conversation_id"),
            ),
        )

    def _runtime_get_config(self, args: dict[str, Any]) -> McpToolResult:
        _reject_unexpected_args(args, allowed=())
        return McpToolResult(
            ok=True,
            message="runtime config",
            data=self.core_runtime.runtime_get_config(),
        )

    def _runtime_list_loops(self, args: dict[str, Any]) -> McpToolResult:
        _reject_unexpected_args(args, allowed=())
        return McpToolResult(
            ok=True,
            message="runtime loops",
            data={"loops": self.core_runtime.runtime_list_loops()},
        )

    def _runtime_list_recent_runs(self, args: dict[str, Any]) -> McpToolResult:
        return McpToolResult(
            ok=True,
            message="recent runs",
            data={
                "runs": self.core_runtime.runtime_list_recent_runs(
                    conversation_id=_optional_str(args, "conversation_id"),
                    limit=_optional_limit(args, "limit", default=10),
                )
            },
        )

    def _runtime_get_run(self, args: dict[str, Any]) -> McpToolResult:
        return McpToolResult(
            ok=True,
            message="runtime run",
            data=self.core_runtime.runtime_get_run(
                run_id=_required_str(args, "run_id"),
            ),
        )

    def _runtime_add_loop(self, args: dict[str, Any]) -> McpToolResult:
        return McpToolResult(
            ok=True,
            message="runtime loop added",
            data=self.core_runtime.add_loop(
                loop=_required_object(args, "loop"),
                actor=_actor(args),
                run_id=_optional_str(args, "run_id"),
            ),
        )

    def _runtime_update_loop(self, args: dict[str, Any]) -> McpToolResult:
        return McpToolResult(
            ok=True,
            message="runtime loop updated",
            data=self.core_runtime.update_loop(
                loop_id=_required_str(args, "loop_id"),
                updates=_required_object(args, "updates"),
                actor=_actor(args),
                run_id=_optional_str(args, "run_id"),
            ),
        )

    def _runtime_enable_loop(self, args: dict[str, Any]) -> McpToolResult:
        return McpToolResult(
            ok=True,
            message="runtime loop enabled",
            data=self.core_runtime.enable_loop(
                loop_id=_required_str(args, "loop_id"),
                actor=_actor(args),
                run_id=_optional_str(args, "run_id"),
            ),
        )

    def _runtime_disable_loop(self, args: dict[str, Any]) -> McpToolResult:
        return McpToolResult(
            ok=True,
            message="runtime loop disabled",
            data=self.core_runtime.disable_loop(
                loop_id=_required_str(args, "loop_id"),
                actor=_actor(args),
                run_id=_optional_str(args, "run_id"),
            ),
        )

    def _channel(self, args: dict[str, Any]) -> str:
        return _optional_str(args, "channel") or self.default_channel


def _as_tool_result(result: ChannelOutboundResult) -> McpToolResult:
    data = dict(result.data)
    if result.external_message_id is not None:
        data.setdefault("message_id", result.external_message_id)
    if result.external_card_id is not None:
        data.setdefault("card_id", result.external_card_id)
    if result.target is not None:
        data.setdefault("target", result.target.as_context())
    return McpToolResult(ok=result.ok, message=result.message, data=data)


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


def _required_object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"{key} must be an object")
    return value


def _optional_limit(payload: dict[str, Any], key: str, *, default: int) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int):
        raise RuntimeError(f"{key} must be an integer")
    return max(1, min(value, 50))


def _actor(payload: dict[str, Any]) -> str:
    return _optional_str(payload, "actor") or "agent:mcp"


def _reject_unexpected_args(payload: dict[str, Any], *, allowed: tuple[str, ...]) -> None:
    unexpected = sorted(set(payload) - set(allowed))
    if unexpected:
        raise RuntimeError(f"unexpected arguments: {', '.join(unexpected)}")
