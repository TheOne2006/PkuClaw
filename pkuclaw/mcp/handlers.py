"""Dispatch MCP channel notification tool calls to CoreRuntime."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pkuclaw.channels.base import ChannelOutboundResult
from pkuclaw.core.runtime import CoreRuntime
from pkuclaw.mcp.channel_tools import McpToolResult
from pkuclaw.mcp.schemas import list_tool_schemas


@dataclass
class DaemonMcpToolHandler:
    """Dispatch channel notification tool calls into CoreRuntime."""

    core_runtime: CoreRuntime
    default_channel: str = "feishu"

    def list_tools(self) -> list[dict[str, Any]]:
        """Return MCP tool schemas."""

        return list_tool_schemas()

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        loop_id: str | None = None,
    ) -> McpToolResult:
        """Validate arguments and dispatch by tool name."""

        args = arguments or {}
        if not isinstance(args, dict):
            raise RuntimeError("tool arguments must be an object")
        dispatch: dict[str, Callable[..., McpToolResult]] = {
            "channel_send_text": self._channel_send_text,
            "channel_send_card": self._channel_send_card,
            "channel_send_image": self._channel_send_image,
            "channel_update_card": self._channel_update_card,
        }
        handler = dispatch.get(name)
        if handler is None:
            raise RuntimeError(f"unknown tool: {name}")
        return handler(args, loop_id=loop_id)

    def _channel_send_text(
        self,
        args: dict[str, Any],
        *,
        loop_id: str | None = None,
    ) -> McpToolResult:
        _ensure_only_args(args, {"text"})
        target = self._notification_target(loop_id=loop_id)
        return _as_tool_result(
            self.core_runtime.send_channel_text(
                channel=target["channel"],
                target_type=target["target_type"],
                target_id=target["target_id"],
                text=_required_str(args, "text"),
            )
        )

    def _channel_send_card(
        self,
        args: dict[str, Any],
        *,
        loop_id: str | None = None,
    ) -> McpToolResult:
        _ensure_only_args(args, {"card"})
        target = self._notification_target(loop_id=loop_id)
        return _as_tool_result(
            self.core_runtime.send_channel_card(
                channel=target["channel"],
                target_type=target["target_type"],
                target_id=target["target_id"],
                card=_required_object(args, "card"),
            )
        )

    def _channel_send_image(
        self,
        args: dict[str, Any],
        *,
        loop_id: str | None = None,
    ) -> McpToolResult:
        _ensure_only_args(args, {"image_path"})
        target = self._notification_target(loop_id=loop_id)
        return _as_tool_result(
            self.core_runtime.send_channel_image(
                channel=target["channel"],
                target_type=target["target_type"],
                target_id=target["target_id"],
                image_path=_required_str(args, "image_path"),
            )
        )

    def _channel_update_card(
        self,
        args: dict[str, Any],
        *,
        loop_id: str | None = None,
    ) -> McpToolResult:
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

    def _channel(self, args: dict[str, Any]) -> str:
        return _optional_str(args, "channel") or self.default_channel

    def _notification_target(self, *, loop_id: str | None = None) -> dict[str, str]:
        """Resolve the configured default notification target."""

        target = self.core_runtime.resolve_notification_target(loop_id=loop_id)
        if target is None:
            raise RuntimeError(
                "no default notification target configured; set "
                "notifications.default_channel/default_target_type/default_target_id"
            )
        return target


def _as_tool_result(result: ChannelOutboundResult) -> McpToolResult:
    """Convert a channel outbox result into an MCP tool result."""

    data = dict(result.data)
    if result.external_message_id is not None:
        data.setdefault("message_id", result.external_message_id)
    if result.external_card_id is not None:
        data.setdefault("card_id", result.external_card_id)
    if result.target is not None:
        data.setdefault("target", result.target.as_context())
    return McpToolResult(ok=result.ok, message=result.message, data=data)


def _ensure_only_args(payload: dict[str, Any], allowed: set[str]) -> None:
    """Reject arguments outside the fixed send-tool schemas."""
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise RuntimeError(
            "unsupported arguments for fixed-target notification tool: "
            + ", ".join(unexpected)
        )


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
