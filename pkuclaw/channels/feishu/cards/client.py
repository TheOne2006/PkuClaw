from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pkuclaw.core import logging as log


@dataclass(frozen=True)
class FeishuSentCard:
    message_id: str
    card_id: str


class FeishuCardKitClient:
    def __init__(
        self,
        *,
        lark: Any,
        client: Any,
        create_message_request: Any,
        create_message_request_body: Any,
        create_card_request: Any,
        create_card_request_body: Any,
        update_card_request: Any,
        update_card_request_body: Any,
        card_model: Any,
    ) -> None:
        self.lark = lark
        self.client = client
        self.create_message_request = create_message_request
        self.create_message_request_body = create_message_request_body
        self.create_card_request = create_card_request
        self.create_card_request_body = create_card_request_body
        self.update_card_request = update_card_request
        self.update_card_request_body = update_card_request_body
        self.card_model = card_model

    def send_card(
        self,
        *,
        receive_id_type: str,
        receive_id: str,
        card: dict[str, Any],
    ) -> FeishuSentCard:
        card_id = self.create_card(card)
        request = (
            self.create_message_request.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                self.create_message_request_body.builder()
                .receive_id(receive_id)
                .msg_type("interactive")
                .content(_card_message_content(card_id))
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.create(request)
        self._raise_if_failed(response, "client.im.v1.message.create")
        message_id = _response_message_id(response)
        if not message_id:
            raise RuntimeError("Feishu create message response missing message_id")
        return FeishuSentCard(message_id=message_id, card_id=card_id)

    def create_card(self, card: dict[str, Any]) -> str:
        request = (
            self.create_card_request.builder()
            .request_body(
                self.create_card_request_body.builder()
                .type("card_json")
                .data(_card_data(card))
                .build()
            )
            .build()
        )
        response = self.client.cardkit.v1.card.create(request)
        self._raise_if_failed(response, "client.cardkit.v1.card.create")
        card_id = _response_card_id(response)
        if not card_id:
            raise RuntimeError("Feishu create card response missing card_id")
        return card_id

    def update_card(
        self,
        *,
        card_id: str,
        card: dict[str, Any],
        sequence: int,
    ) -> None:
        card_payload = (
            self.card_model.builder()
            .type("card_json")
            .data(_card_data(card))
            .build()
        )
        request = (
            self.update_card_request.builder()
            .card_id(card_id)
            .request_body(
                self.update_card_request_body.builder()
                .card(card_payload)
                .uuid(f"pkuclaw_{card_id}_{sequence}")
                .sequence(sequence)
                .build()
            )
            .build()
        )
        response = self.client.cardkit.v1.card.update(request)
        self._raise_if_failed(response, "client.cardkit.v1.card.update")

    def _raise_if_failed(self, response: Any, operation: str) -> None:
        if response.success():
            return
        log_id = response.get_log_id()
        raise RuntimeError(
            f"{operation} failed, code={response.code}, msg={response.msg}, "
            f"log_id={log_id}, resp={_format_raw_response(self.lark, response)}"
        )


def _card_data(card: dict[str, Any]) -> str:
    return json.dumps(card, ensure_ascii=False, separators=(",", ":"))


def _card_message_content(card_id: str) -> str:
    return json.dumps(
        {
            "type": "card",
            "data": {
                "card_id": card_id,
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _response_message_id(response: Any) -> str | None:
    data = getattr(response, "data", None)
    message_id = getattr(data, "message_id", None)
    return message_id if isinstance(message_id, str) and message_id else None


def _response_card_id(response: Any) -> str | None:
    data = getattr(response, "data", None)
    card_id = getattr(data, "card_id", None)
    return card_id if isinstance(card_id, str) and card_id else None


def _format_raw_response(lark: Any, response: Any) -> str:
    raw = getattr(response, "raw", None)
    content = getattr(raw, "content", None)
    if not content:
        return ""
    try:
        return json.dumps(json.loads(content), ensure_ascii=False)
    except (TypeError, json.JSONDecodeError, UnicodeDecodeError):
        if isinstance(content, bytes):
            return str(content, lark.UTF_8, errors="replace")
        return str(content)
