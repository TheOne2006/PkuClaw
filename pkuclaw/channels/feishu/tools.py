"""CoreRuntime channel outbox 的飞书实现。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from pkuclaw.channels.base import (
    ChannelOutboundResult,
    ChannelTarget,
)

from .cards import FeishuCardKitClient, FeishuCardRenderer


@dataclass
class FeishuChannelOutboundBackend:
    """Feishu implementation of the CoreRuntime-owned channel outbox contract."""

    channel: ClassVar[str] = "feishu"

    client: FeishuCardKitClient
    renderer: FeishuCardRenderer

    def send_text(
        self,
        *,
        target: ChannelTarget,
        text: str,
        title: str | None = None,
    ) -> ChannelOutboundResult:
        """发送文本内容。"""
        sent = self.client.send_card(
            receive_id_type=target.target_type,
            receive_id=target.target_id,
            card=self.renderer.control_card(title=title or "PkuClaw", body=text),
        )
        return ChannelOutboundResult(
            ok=True,
            message="text sent",
            target=target,
            external_message_id=sent.message_id,
            external_card_id=sent.card_id,
            data={"message_id": sent.message_id, "card_id": sent.card_id},
        )

    def send_card(
        self,
        *,
        target: ChannelTarget,
        card: dict[str, Any],
    ) -> ChannelOutboundResult:
        """发送结构化卡片。"""
        sent = self.client.send_card(
            receive_id_type=target.target_type,
            receive_id=target.target_id,
            card=card,
        )
        return ChannelOutboundResult(
            ok=True,
            message="card sent",
            target=target,
            external_message_id=sent.message_id,
            external_card_id=sent.card_id,
            data={"message_id": sent.message_id, "card_id": sent.card_id},
        )

    def send_image(
        self,
        *,
        target: ChannelTarget,
        image_path: str,
        caption: str | None = None,
    ) -> ChannelOutboundResult:
        """发送图片内容。"""
        caption_result = _send_caption(self, target=target, caption=caption)
        sent = self.client.send_image(
            receive_id_type=target.target_type,
            receive_id=target.target_id,
            image_path=image_path,
        )
        return ChannelOutboundResult(
            ok=True,
            message="image sent",
            target=target,
            external_message_id=sent.message_id,
            data={
                "image_path": image_path,
                "image_key": sent.resource_key,
                "message_id": sent.message_id,
                **_caption_data(caption_result),
            },
        )

    def send_file(
        self,
        *,
        target: ChannelTarget,
        file_path: str,
        caption: str | None = None,
    ) -> ChannelOutboundResult:
        """发送文件内容。"""
        caption_result = _send_caption(self, target=target, caption=caption)
        sent = self.client.send_file(
            receive_id_type=target.target_type,
            receive_id=target.target_id,
            file_path=file_path,
        )
        return ChannelOutboundResult(
            ok=True,
            message="file sent",
            target=target,
            external_message_id=sent.message_id,
            data={
                "file_path": file_path,
                "file_key": sent.resource_key,
                "message_id": sent.message_id,
                **_caption_data(caption_result),
            },
        )

    def update_card(
        self,
        *,
        card_id: str,
        card: dict[str, Any],
        sequence: int,
    ) -> ChannelOutboundResult:
        """更新已发送的卡片。"""
        self.client.update_card(card_id=card_id, card=card, sequence=sequence)
        return ChannelOutboundResult(
            ok=True,
            message="card updated",
            external_card_id=card_id,
            data={"card_id": card_id, "sequence": sequence},
        )


def _send_caption(
    backend: FeishuChannelOutboundBackend,
    *,
    target: ChannelTarget,
    caption: str | None,
) -> ChannelOutboundResult | None:
    """Send an optional caption before media delivery."""

    if not isinstance(caption, str) or not caption.strip():
        return None
    return backend.send_text(target=target, text=caption.strip())


def _caption_data(result: ChannelOutboundResult | None) -> dict[str, Any]:
    """Return compact caption delivery metadata."""

    if result is None:
        return {}
    data: dict[str, Any] = {}
    if result.external_message_id:
        data["caption_message_id"] = result.external_message_id
    if result.external_card_id:
        data["caption_card_id"] = result.external_card_id
    return data
