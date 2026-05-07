"""定义 channel adapter、入站消息、出站后端和事件 sink 协议。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from pkuclaw.core.models import AgentEventSink
    from pkuclaw.core.store import Store


@dataclass(frozen=True)
class ChannelTarget:
    """A channel-neutral destination for user-visible messages or card updates."""

    channel: str
    target_type: str
    target_id: str
    thread_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_context(self) -> dict[str, Any]:
        """转换为可序列化的 channel context 字典。"""
        context: dict[str, Any] = {
            "channel": self.channel,
            "target_type": self.target_type,
            "target_id": self.target_id,
        }
        if self.thread_id:
            context["thread_id"] = self.thread_id
        if self.metadata:
            context["metadata"] = dict(self.metadata)
        return context


@dataclass(frozen=True)
class ChannelInboundMessage:
    """A normalized inbound event produced by a thin channel adapter."""

    channel: str
    conversation_id: str
    text: str
    sender_id: str | None = None
    target: ChannelTarget | None = None
    event_key: str | None = None
    external_message_id: str | None = None
    raw: Any | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def channel_context(self) -> dict[str, Any]:
        """转换为 CoreRuntime/Agent prompt 可使用的 channel 上下文字典。"""
        context: dict[str, Any] = {"channel": self.channel}
        if self.sender_id:
            context["sender_id"] = self.sender_id
        if self.target is not None:
            context["target"] = self.target.as_context()
        if self.external_message_id:
            context["external_message_id"] = self.external_message_id
        if self.metadata:
            context["metadata"] = dict(self.metadata)
        return context


@dataclass(frozen=True)
class ChannelOutboundResult:
    """channel outbox 操作的统一返回对象。"""
    ok: bool
    message: str
    target: ChannelTarget | None = None
    external_message_id: str | None = None
    external_card_id: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)


class ChannelOutboundBackend(Protocol):
    """Backend contract for CoreRuntime-owned channel outbox operations."""

    channel: str

    def send_text(self, *, target: ChannelTarget, text: str) -> ChannelOutboundResult:
        """Send text to a channel target."""

    def send_card(
        self,
        *,
        target: ChannelTarget,
        card: dict[str, Any],
    ) -> ChannelOutboundResult:
        """Send a structured card to a channel target."""

    def send_image(
        self,
        *,
        target: ChannelTarget,
        image_path: str,
    ) -> ChannelOutboundResult:
        """Send an image to a channel target."""

    def update_card(
        self,
        *,
        card_id: str,
        card: dict[str, Any],
        sequence: int,
    ) -> ChannelOutboundResult:
        """Update a previously sent card."""


class ChannelEventSinkFactory(Protocol):
    """Factory for channel-specific renderers of AgentEvent streams."""

    def create_realtime_sink(
        self,
        *,
        target: ChannelTarget,
        run_id: str,
        store: Store,
    ) -> AgentEventSink:
        """Create a sink that renders one realtime run to a channel target."""


class ChannelAdapter(Protocol):
    """Transport adapter boundary for Feishu/Web/WeChat implementations."""

    channel: str

    def start(self) -> None:
        """Start receiving platform events and forwarding ChannelInboundMessage."""
