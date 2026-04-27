from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pkuclaw.mcp import ChannelToolResult

from .cards import FeishuCardKitClient, FeishuCardRenderer


@dataclass
class FeishuChannelToolBackend:
    client: FeishuCardKitClient
    renderer: FeishuCardRenderer

    def channel_send_text(
        self,
        *,
        target_id: str,
        text: str,
        target_type: str = "chat_id",
    ) -> ChannelToolResult:
        sent = self.client.send_card(
            receive_id_type=target_type,
            receive_id=target_id,
            card=self.renderer.control_card(title="PkuClaw", body=text),
        )
        return ChannelToolResult(
            ok=True,
            message="text sent",
            data={"message_id": sent.message_id, "card_id": sent.card_id},
        )

    def channel_send_card(
        self,
        *,
        target_id: str,
        card: dict[str, Any],
        target_type: str = "chat_id",
    ) -> ChannelToolResult:
        sent = self.client.send_card(
            receive_id_type=target_type,
            receive_id=target_id,
            card=card,
        )
        return ChannelToolResult(
            ok=True,
            message="card sent",
            data={"message_id": sent.message_id, "card_id": sent.card_id},
        )

    def channel_send_image(
        self,
        *,
        target_id: str,
        image_path: str,
        target_type: str = "chat_id",
    ) -> ChannelToolResult:
        return ChannelToolResult(
            ok=False,
            message="Feishu image upload is not implemented in V1",
            data={
                "target_id": target_id,
                "target_type": target_type,
                "image_path": image_path,
            },
        )

    def channel_update_card(
        self,
        *,
        card_id: str,
        card: dict[str, Any],
        sequence: int,
    ) -> ChannelToolResult:
        self.client.update_card(card_id=card_id, card=card, sequence=sequence)
        return ChannelToolResult(
            ok=True,
            message="card updated",
            data={"card_id": card_id, "sequence": sequence},
        )
