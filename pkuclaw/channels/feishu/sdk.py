"""集中加载 lark-oapi 类型并创建飞书 SDK 客户端。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pkuclaw.config import Settings
from pkuclaw.core import logging as log

from .cards import FeishuCardKitClient


@dataclass(frozen=True)
class FeishuSdk:
    """集中保存 lark-oapi 中 PkuClaw 需要的 SDK 类型。"""
    lark: Any
    card_model: Any
    create_card_request: Any
    create_card_request_body: Any
    create_image_request: Any
    create_image_request_body: Any
    create_file_request: Any
    create_file_request_body: Any
    create_message_request: Any
    create_message_request_body: Any
    update_card_request: Any
    update_card_request_body: Any
    card_action_response: Any


def load_feishu_sdk() -> FeishuSdk:
    """导入 lark-oapi 相关类型，并在缺依赖时给出友好错误。"""
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
            CreateFileRequest,
            CreateFileRequestBody,
            CreateImageRequest,
            CreateImageRequestBody,
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
        create_image_request=CreateImageRequest,
        create_image_request_body=CreateImageRequestBody,
        create_file_request=CreateFileRequest,
        create_file_request_body=CreateFileRequestBody,
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
    """根据配置和凭据创建飞书开放平台 API client。"""
    return (
        sdk.lark.Client.builder()
        .app_id(settings.feishu.app_id)
        .app_secret(app_secret)
        .domain(settings.feishu.api_base)
        .build()
    )


def build_cardkit_client(*, sdk: FeishuSdk, api_client: Any) -> FeishuCardKitClient:
    """把飞书 SDK 类型打包成 PkuClaw CardKit client。"""
    return FeishuCardKitClient(
        lark=sdk.lark,
        client=api_client,
        create_message_request=sdk.create_message_request,
        create_message_request_body=sdk.create_message_request_body,
        create_card_request=sdk.create_card_request,
        create_card_request_body=sdk.create_card_request_body,
        create_image_request=sdk.create_image_request,
        create_image_request_body=sdk.create_image_request_body,
        create_file_request=sdk.create_file_request,
        create_file_request_body=sdk.create_file_request_body,
        update_card_request=sdk.update_card_request,
        update_card_request_body=sdk.update_card_request_body,
        card_model=sdk.card_model,
    )


def build_event_handler(*, sdk: FeishuSdk, handlers: Any) -> Any:
    """注册飞书消息、菜单和卡片回调处理函数。"""
    return (
        sdk.lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(handlers.on_message)
        .register_p2_im_message_message_read_v1(lambda _data: None)
        .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(lambda _data: None)
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
    """创建飞书 websocket client，并修正 CardKit callback frame 类型。"""
    class CardCallbackClient(sdk.lark.ws.Client):
        """修正 CardKit websocket callback frame 类型的 SDK 子类。"""
        async def _handle_data_frame(self, frame: Any) -> Any:
            """把飞书 card frame 转为 event frame 后交给 SDK 默认处理。"""
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
