from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pkuclaw.backbone import TeachingBackbone
from pkuclaw.code_agents import build_code_agent
from pkuclaw.config import Settings
from pkuclaw.connectors.pku3b import Pku3b
from pkuclaw.core import logging as log
from pkuclaw.core.app import CoreLoop
from pkuclaw.core.control import mode_label
from pkuclaw.core.models import ChannelMessage, merge_agent_settings
from pkuclaw.core.store import Store
from pkuclaw.runtime_config import RuntimeConfigLoader
from pkuclaw.channels.feishu_cards import (
    FeishuCardRenderer,
    FeishuMessageClient,
    FeishuRunCardSink,
)


def run_feishu_bot(settings: Settings) -> None:
    """Start the Feishu websocket bot and reply to text messages."""
    log.stage("Booting PkuClaw Feishu gateway")
    log.startup_table(
        "Runtime",
        [
            ("config", settings.config_path),
            ("data_dir", settings.app.data_dir),
            ("runtime_config_dir", settings.app.runtime_config_dir),
            ("feishu_mode", settings.feishu.event_mode),
            ("feishu_app_id", settings.feishu.app_id),
            ("code_agent", settings.code_agent.provider),
            ("codex_bin", settings.codex.bin),
            ("codex_sandbox", settings.codex.sandbox),
            ("codex_timeout", f"{settings.codex.timeout_seconds}s"),
            ("max_workers", settings.codex.max_concurrent_runs),
            ("pku3b_bin", settings.pku3b.bin),
        ],
    )

    if settings.feishu.event_mode != "websocket":
        raise RuntimeError(
            f"unsupported Feishu event mode: {settings.feishu.event_mode}"
        )

    log.stage("Loading Feishu SDK")
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
            PatchMessageRequest,
            PatchMessageRequestBody,
        )
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTriggerResponse,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "missing dependency: run `uv sync` to install lark-oapi"
        ) from exc
    log.ok("Feishu SDK loaded")

    log.stage("Resolving Feishu credentials")
    app_secret = settings.feishu.resolve_app_secret()
    log.ok("Feishu credentials resolved")

    log.stage("Building Feishu API client")
    api_client = (
        lark.Client.builder()
        .app_id(settings.feishu.app_id)
        .app_secret(app_secret)
        .domain(settings.feishu.api_base)
        .build()
    )
    log.ok("Feishu API client ready")
    message_client = FeishuMessageClient(
        lark=lark,
        client=api_client,
        create_message_request=CreateMessageRequest,
        create_message_request_body=CreateMessageRequestBody,
        patch_message_request=PatchMessageRequest,
        patch_message_request_body=PatchMessageRequestBody,
    )
    card_renderer = FeishuCardRenderer()

    log.stage("Opening local state store")
    store = Store(settings.app.data_dir / "pkuclaw.db")
    log.ok(
        "State store ready: "
        f"conversations={store.active_conversation_count()}, "
        f"runs={sum(store.counts_by_status().values())}"
    )

    log.stage("Building core loop")
    runtime_config = RuntimeConfigLoader(settings.app.runtime_config_dir)
    code_agent = build_code_agent(
        settings=settings,
        store=store,
        runtime_config=runtime_config,
    )
    teaching_backbone = TeachingBackbone(
        pku3b=Pku3b(settings.pku3b.bin),
        snapshot_dir=settings.app.data_dir / "snapshots",
    )
    core_loop = CoreLoop(
        store=store,
        code_agent=code_agent,
        runtime_config=runtime_config,
        teaching_backbone=teaching_backbone,
    )
    log.ok(f"Core loop ready: channels -> core -> backbone/{code_agent.name}")

    executor = ThreadPoolExecutor(max_workers=settings.codex.max_concurrent_runs)
    log.ok(
        "Code-agent worker pool ready: "
        f"provider={code_agent.name}, max_workers={settings.codex.max_concurrent_runs}"
    )
    chat_locks: dict[str, threading.Lock] = {}
    chat_locks_lock = threading.Lock()

    def chat_lock(chat_id: str) -> threading.Lock:
        with chat_locks_lock:
            if chat_id not in chat_locks:
                chat_locks[chat_id] = threading.Lock()
            return chat_locks[chat_id]

    def on_message(data: Any) -> None:
        event = getattr(data, "event", None)
        message = getattr(event, "message", None)
        if message is None or getattr(message, "message_type", None) != "text":
            return

        chat_id = getattr(message, "chat_id", None)
        sender_id = _extract_sender_open_id(event)
        if not chat_id or not sender_id:
            return

        text = _extract_text_content(getattr(message, "content", ""))
        dispatch = core_loop.ingest(
            ChannelMessage(
                channel="feishu",
                conversation_id=_feishu_conversation_id(sender_id),
                sender_id=sender_id,
                text=text,
                raw=data,
            )
        )
        log.event(
            "message received: "
            f"chat={_short_id(chat_id)}, sender={_short_id(sender_id)}, "
            f"run={dispatch.run_id or 'local'}, chars={len(text)}, "
            f"local={dispatch.handled_locally}"
        )
        if dispatch.run_id is None or dispatch.plan is None:
            _send_control_card(
                message_client=message_client,
                renderer=card_renderer,
                receive_id_type="chat_id",
                receive_id=chat_id,
                text=dispatch.reply_text,
            )
            log.ok("local control card sent")
            return

        run = core_loop.store.get_run(dispatch.run_id)
        sink = FeishuRunCardSink(
            client=message_client,
            renderer=card_renderer,
            store=core_loop.store,
            chat_id=chat_id,
            run_id=dispatch.run_id,
            user_text=run.user_text,
            ack=dispatch.reply_text,
            agent_context=_agent_context(core_loop, run.conversation_id),
        )
        sink.start()
        executor.submit(
            _process_code_agent_run,
            core_loop,
            chat_lock(chat_id),
            chat_id,
            dispatch.run_id,
            dispatch.plan,
            sink,
        )

    def on_bot_menu(data: Any) -> None:
        event = getattr(data, "event", None)
        event_key = getattr(event, "event_key", None)
        operator = getattr(event, "operator", None)
        operator_id = getattr(operator, "operator_id", None)
        open_id = getattr(operator_id, "open_id", None)
        if not event_key or not open_id:
            log.warn("bot menu event missing event_key/open_id")
            return

        dispatch = core_loop.ingest(
            ChannelMessage(
                channel="feishu",
                conversation_id=_feishu_conversation_id(open_id),
                sender_id=open_id,
                text="",
                event_key=event_key,
                raw=data,
            )
        )
        log.event(
            "menu event received: "
            f"sender={_short_id(open_id)}, key={event_key}, "
            f"local={dispatch.handled_locally}"
        )
        _send_control_card(
            message_client=message_client,
            renderer=card_renderer,
            receive_id_type="open_id",
            receive_id=open_id,
            text=dispatch.reply_text,
        )
        log.ok(f"menu card sent: key={event_key}, sender={_short_id(open_id)}")

    def on_card_action(data: Any) -> Any:
        event = getattr(data, "event", None)
        action = getattr(event, "action", None)
        value = getattr(action, "value", None) or {}
        operator = getattr(event, "operator", None)
        open_id = getattr(operator, "open_id", None)
        event_key = value.get("event_key") if isinstance(value, dict) else None
        if not event_key or not open_id:
            log.warn("card action missing event_key/open_id")
            return P2CardActionTriggerResponse(
                {"toast": {"type": "error", "content": "无法识别这个卡片动作"}}
            )

        receive_id_type, receive_id = _card_action_target(event, open_id)
        dispatch = core_loop.ingest(
            ChannelMessage(
                channel="feishu",
                conversation_id=_feishu_conversation_id(open_id),
                sender_id=open_id,
                text="",
                event_key=event_key,
                raw=data,
            )
        )
        log.event(
            "card action received: "
            f"sender={_short_id(open_id)}, key={event_key}, "
            f"target={receive_id_type}:{_short_id(receive_id)}"
        )
        _send_control_card(
            message_client=message_client,
            renderer=card_renderer,
            receive_id_type=receive_id_type,
            receive_id=receive_id,
            text=dispatch.reply_text,
        )
        return P2CardActionTriggerResponse(
            {"toast": {"type": "success", "content": "已处理"}}
        )

    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .register_p2_im_message_message_read_v1(lambda _data: None)
        .register_p2_application_bot_menu_v6(on_bot_menu)
        .register_p2_card_action_trigger(on_card_action)
        .build()
    )
    log.ok(
        "Feishu event handlers registered: "
        "message_receive, bot_menu, card_action, message_read(no-op)"
    )

    log.stage("Connecting Feishu websocket")
    client = lark.ws.Client(
        settings.feishu.app_id,
        app_secret,
        event_handler=event_handler,
        domain=settings.feishu.api_base,
        log_level=lark.LogLevel.INFO,
    )
    log.ok("Startup complete; waiting for Feishu messages")
    client.start()


def _process_code_agent_run(
    core_loop: CoreLoop,
    lock: threading.Lock,
    chat_id: str,
    run_id: str,
    plan: Any,
    sink: FeishuRunCardSink,
) -> None:
    with lock:
        try:
            log.stage(
                f"Code-agent run starting: run={run_id}, chat={_short_id(chat_id)}"
            )
            result = core_loop.run_code_agent(run_id, plan, sink)
            log.ok(
                "Code-agent run completed: "
                f"run={run_id}, status={result.status}, "
                f"thread={result.session_id or 'none'}, result={result.result_path}"
            )
        except Exception as exc:
            core_loop.store.mark_run_failed(run_id, str(exc))
            sink.fail(str(exc))
            log.fail(f"Code-agent run failed: run={run_id}, error={exc}")


def _extract_text_content(content: str) -> str:
    if not content:
        return ""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content
    text = payload.get("text")
    return text if isinstance(text, str) else content


def _extract_sender_open_id(event: Any) -> str | None:
    sender = getattr(event, "sender", None)
    sender_id = getattr(sender, "sender_id", None)
    open_id = getattr(sender_id, "open_id", None)
    return open_id if isinstance(open_id, str) and open_id else None


def _feishu_conversation_id(open_id: str) -> str:
    return f"feishu:user:{open_id}"


def _send_control_card(
    *,
    message_client: FeishuMessageClient,
    renderer: FeishuCardRenderer,
    receive_id_type: str,
    receive_id: str,
    text: str,
) -> None:
    message_client.send_card(
        receive_id_type=receive_id_type,
        receive_id=receive_id,
        card=renderer.control_card(title="PkuClaw", body=text),
    )


def _agent_context(core_loop: CoreLoop, conversation_id: str) -> dict[str, str]:
    conversation = core_loop.store.ensure_conversation(conversation_id)
    runtime = core_loop.runtime_config.read()
    settings = merge_agent_settings(runtime.code_agent, conversation.agent_settings)
    mode = settings.mode or "standard"
    return {
        "provider": settings.provider or "codex",
        "mode": mode_label(mode),
        "model": settings.model or "默认",
        "reasoning": settings.reasoning_effort or "默认",
    }


def _card_action_target(event: Any, open_id: str) -> tuple[str, str]:
    context = getattr(event, "context", None)
    chat_id = getattr(context, "open_chat_id", None)
    if isinstance(chat_id, str) and chat_id:
        return "chat_id", chat_id
    return "open_id", open_id


def _short_id(value: str) -> str:
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-4:]}"
