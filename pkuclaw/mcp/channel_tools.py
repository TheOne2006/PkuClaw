from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ChannelToolResult:
    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)


class ChannelToolBackend(Protocol):
    def channel_send_text(
        self,
        *,
        target_id: str,
        text: str,
        target_type: str = "chat_id",
    ) -> ChannelToolResult:
        """Send text through the active channel backend."""

    def channel_send_card(
        self,
        *,
        target_id: str,
        card: dict[str, Any],
        target_type: str = "chat_id",
    ) -> ChannelToolResult:
        """Send a structured card through the active channel backend."""

    def channel_send_image(
        self,
        *,
        target_id: str,
        image_path: str,
        target_type: str = "chat_id",
    ) -> ChannelToolResult:
        """Send an image through the active channel backend."""

    def channel_update_card(
        self,
        *,
        card_id: str,
        card: dict[str, Any],
        sequence: int,
    ) -> ChannelToolResult:
        """Update a previously sent card."""
