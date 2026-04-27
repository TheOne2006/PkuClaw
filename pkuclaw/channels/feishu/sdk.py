from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pkuclaw.config import Settings
from pkuclaw.core import logging as log

from .cards import FeishuCardKitClient


@dataclass(frozen=True)
class FeishuSdk:
    lark: Any
    card_model: Any
    create_card_request: Any
    create_card_request_body: Any
    create_message_request: Any
    create_message_request_body: Any
    update_card_request: Any
    update_card_request_body: Any
    card_action_response: Any


def load_feishu_sdk() -> FeishuSdk:
    try:
        import lark_oapi as lark
        from lark_oapi.api.cardkit.v1 import (
            Card,
            CreateCardRequest,
            CreateCardRequestBody,
            UpdateCardRequest,
            UpdateCardRequestBody,
        )
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTriggerResponse,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "missing dependency: run `uv sync` to install lark-oapi"
        ) from exc

    return FeishuSdk(
        lark=lark,
        card_model=Card,
        create_card_request=CreateCardRequest,
        create_card_request_body=CreateCardRequestBody,
        create_message_request=CreateMessageRequest,
        create_message_request_body=CreateMessageRequestBody,
        update_card_request=UpdateCardRequest,
        update_card_request_body=UpdateCardRequestBody,
        card_action_response=P2CardActionTriggerResponse,
    )


def build_api_client(
    *,
    sdk: FeishuSdk,
    settings: Settings,
    app_secret: str,
) -> Any:
    return (
        sdk.lark.Client.builder()
        .app_id(settings.feishu.app_id)
        .app_secret(app_secret)
        .domain(settings.feishu.api_base)
        .build()
    )


def build_cardkit_client(*, sdk: FeishuSdk, api_client: Any) -> FeishuCardKitClient:
    return FeishuCardKitClient(
        lark=sdk.lark,
        client=api_client,
        create_message_request=sdk.create_message_request,
        create_message_request_body=sdk.create_message_request_body,
        create_card_request=sdk.create_card_request,
        create_card_request_body=sdk.create_card_request_body,
        update_card_request=sdk.update_card_request,
        update_card_request_body=sdk.update_card_request_body,
        card_model=sdk.card_model,
    )


def build_event_handler(*, sdk: FeishuSdk, handlers: Any) -> Any:
    return (
        sdk.lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(handlers.on_message)
        .register_p2_im_message_message_read_v1(lambda _data: None)
        .register_p2_application_bot_menu_v6(handlers.on_bot_menu)
        .register_p2_card_action_trigger(handlers.on_card_action)
        .build()
    )


def new_ws_client(
    *,
    sdk: FeishuSdk,
    app_id: str,
    app_secret: str,
    event_handler: Any,
    domain: str,
) -> Any:
    class CardCallbackClient(sdk.lark.ws.Client):
        async def _handle_data_frame(self, frame: Any) -> Any:
            for header in frame.headers:
                if header.key == "type" and header.value == "card":
                    header.value = "event"
                    log.event("Feishu card callback frame received")
                    break
            return await super()._handle_data_frame(frame)

    return CardCallbackClient(
        app_id,
        app_secret,
        event_handler=event_handler,
        domain=domain,
        log_level=sdk.lark.LogLevel.INFO,
    )
