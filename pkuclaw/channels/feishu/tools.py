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

    def send_text(self, *, target: ChannelTarget, text: str) -> ChannelOutboundResult:
        sent = self.client.send_card(
            receive_id_type=target.target_type,
            receive_id=target.target_id,
            card=self.renderer.control_card(title="PkuClaw", body=text),
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
    ) -> ChannelOutboundResult:
        return ChannelOutboundResult(
            ok=False,
            message="Feishu image upload is not implemented in V1",
            target=target,
            data={
                "target_id": target.target_id,
                "target_type": target.target_type,
                "image_path": image_path,
            },
        )

    def update_card(
        self,
        *,
        card_id: str,
        card: dict[str, Any],
        sequence: int,
    ) -> ChannelOutboundResult:
        self.client.update_card(card_id=card_id, card=card, sequence=sequence)
        return ChannelOutboundResult(
            ok=True,
            message="card updated",
            external_card_id=card_id,
            data={"card_id": card_id, "sequence": sequence},
        )
