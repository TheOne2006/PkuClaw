"""组装飞书 websocket gateway，并把它连接到 CoreRuntime。"""
from __future__ import annotations

from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Any, ClassVar

from pkuclaw.config import Settings
from pkuclaw.core import logging as log
from pkuclaw.core.runtime import CoreRuntime

from .cards import FeishuCardKitClient, FeishuCardRenderer
from .handlers import FeishuEventHandlers
from .sdk import (
    FeishuSdk,
    build_api_client,
    build_cardkit_client,
    build_event_handler,
    load_feishu_sdk,
    new_ws_client,
)
from .tools import FeishuChannelOutboundBackend


@dataclass
class FeishuRealtimeGateway:
    """Thin Feishu websocket transport adapter around an existing CoreRuntime."""

    channel: ClassVar[str] = "feishu"

    settings: Settings
    core_runtime: CoreRuntime
    run_executor: Executor
    callback_executor: Executor
    sdk: FeishuSdk
    app_secret: str
    api_client: Any
    message_client: FeishuCardKitClient
    card_renderer: FeishuCardRenderer
    event_handler: Any
    channel_backend: FeishuChannelOutboundBackend

    def start(self) -> None:
        """Connect the Feishu websocket and block until the SDK client returns."""

        log.stage("Connecting Feishu websocket")
        client = new_ws_client(
            sdk=self.sdk,
            app_id=self.settings.feishu.app_id,
            app_secret=self.app_secret,
            event_handler=self.event_handler,
            domain=self.settings.feishu.api_base,
        )
        log.ok("Startup complete; waiting for Feishu messages")
        client.start()


def build_feishu_realtime_gateway(
    *,
    settings: Settings,
    core_runtime: CoreRuntime,
    run_executor: Executor,
    callback_executor: Executor,
) -> FeishuRealtimeGateway:
    """Build Feishu SDK clients, renderer, handlers, and websocket adapter."""

    _log_gateway(settings)
    _require_websocket_mode(settings)

    log.stage("Loading Feishu SDK")
    sdk = load_feishu_sdk()
    log.ok("Feishu SDK loaded")

    log.stage("Resolving Feishu credentials")
    app_secret = settings.feishu.resolve_app_secret()
    log.ok("Feishu credentials resolved")

    log.stage("Building Feishu API client")
    api_client = build_api_client(
        sdk=sdk,
        settings=settings,
        app_secret=app_secret,
    )
    message_client = build_cardkit_client(sdk=sdk, api_client=api_client)
    card_renderer = FeishuCardRenderer()
    channel_backend = FeishuChannelOutboundBackend(
        client=message_client,
        renderer=card_renderer,
    )
    log.ok("Feishu API client ready")

    handlers = FeishuEventHandlers(
        settings=settings,
        core_runtime=core_runtime,
        message_client=message_client,
        card_renderer=card_renderer,
        card_action_response_cls=sdk.card_action_response,
        executor=run_executor,
        callback_executor=callback_executor,
    )
    event_handler = build_event_handler(sdk=sdk, handlers=handlers)
    log.ok(
        "Feishu event handlers registered: "
        "message_receive, bot_menu, card_action, message_read(no-op)"
    )

    return FeishuRealtimeGateway(
        settings=settings,
        core_runtime=core_runtime,
        run_executor=run_executor,
        callback_executor=callback_executor,
        sdk=sdk,
        app_secret=app_secret,
        api_client=api_client,
        message_client=message_client,
        card_renderer=card_renderer,
        event_handler=event_handler,
        channel_backend=channel_backend,
    )


def _log_gateway(settings: Settings) -> None:
    """输出飞书 gateway 启动配置摘要。"""
    log.stage("Booting Feishu realtime gateway")
    log.startup_table(
        "Feishu",
        [
            ("feishu_mode", settings.feishu.event_mode),
            ("feishu_app_id", settings.feishu.app_id),
            ("feishu_api_base", settings.feishu.api_base),
        ],
    )


def _require_websocket_mode(settings: Settings) -> None:
    """限制当前飞书 adapter 只支持 websocket 模式。"""
    if settings.feishu.event_mode == "websocket":
        return
    raise RuntimeError(f"unsupported Feishu event mode: {settings.feishu.event_mode}")
