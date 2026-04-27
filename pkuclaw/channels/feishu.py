from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pkuclaw.config import Settings
from pkuclaw.backbone import TeachingBackbone
from pkuclaw.connectors.pku3b import Pku3b
from pkuclaw.core import logging as log
from pkuclaw.core.app import CoreLoop
from pkuclaw.core.models import ChannelMessage
from pkuclaw.core.router import classify_message
from pkuclaw.core.store import Store
from pkuclaw.workers.codex import CodexWorker


MAX_FEISHU_TEXT = 3500


def handle_text_message(text: str) -> str:
    """Pure message handler shared by Feishu event code and tests."""
    return classify_message(text).ack


def run_feishu_bot(settings: Settings) -> None:
    """Start the Feishu websocket bot and reply to text messages."""
    log.stage("Booting PkuClaw Feishu gateway")
    log.startup_table(
        "Runtime",
        [
            ("config", settings.config_path),
            ("data_dir", settings.app.data_dir),
            ("feishu_mode", settings.feishu.event_mode),
            ("feishu_app_id", settings.feishu.app_id),
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

    log.stage("Opening local state store")
    store = Store(settings.app.data_dir / "pkuclaw.db")
    log.ok(
        "State store ready: "
        f"conversations={store.active_conversation_count()}, "
        f"runs={sum(store.counts_by_status().values())}"
    )

    log.stage("Building core loop")
    codex_worker = CodexWorker(settings=settings, store=store)
    teaching_backbone = TeachingBackbone(
        pku3b=Pku3b(settings.pku3b.bin),
        snapshot_dir=settings.app.data_dir / "snapshots",
    )
    core_loop = CoreLoop(
        store=store,
        codex_worker=codex_worker,
        teaching_backbone=teaching_backbone,
    )
    log.ok("Core loop ready: channels -> core -> backbone/codex")

    executor = ThreadPoolExecutor(max_workers=settings.codex.max_concurrent_runs)
    log.ok(
        "Codex worker pool ready: "
        f"max_workers={settings.codex.max_concurrent_runs}"
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
        _send_text_message(
            lark=lark,
            client=api_client,
            create_message_request=CreateMessageRequest,
            create_message_request_body=CreateMessageRequestBody,
            receive_id_type="chat_id",
            receive_id=chat_id,
            text=dispatch.reply_text,
        )
        log.ok(f"reply sent: run={dispatch.run_id or 'local'}")
        if dispatch.run_id is None or dispatch.plan is None:
            return
        executor.submit(
            _process_codex_run,
            lark,
            api_client,
            CreateMessageRequest,
            CreateMessageRequestBody,
            core_loop,
            chat_lock(chat_id),
            chat_id,
            dispatch.run_id,
            dispatch.plan,
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
        _send_text_message(
            lark=lark,
            client=api_client,
            create_message_request=CreateMessageRequest,
            create_message_request_body=CreateMessageRequestBody,
            receive_id_type="open_id",
            receive_id=open_id,
            text=dispatch.reply_text,
        )
        log.ok(f"menu reply sent: key={event_key}, sender={_short_id(open_id)}")

    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .register_p2_im_message_message_read_v1(lambda _data: None)
        .register_p2_application_bot_menu_v6(on_bot_menu)
        .build()
    )
    log.ok(
        "Feishu event handlers registered: "
        "message_receive, bot_menu, message_read(no-op)"
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


def _process_codex_run(
    lark: Any,
    api_client: Any,
    create_message_request: Any,
    create_message_request_body: Any,
    core_loop: CoreLoop,
    lock: threading.Lock,
    chat_id: str,
    run_id: str,
    plan: Any,
) -> None:
    with lock:
        try:
            log.stage(f"Codex run starting: run={run_id}, chat={_short_id(chat_id)}")
            result = core_loop.run_worker(run_id, plan)
            text = _format_codex_reply(result.response_text, result_path=result.result_path)
            log.ok(
                "Codex run completed: "
                f"run={run_id}, status={result.status}, "
                f"thread={result.session_id or 'none'}, result={result.result_path}"
            )
        except Exception as exc:
            core_loop.store.mark_run_failed(run_id, str(exc))
            text = f"Codex 处理失败：{exc}"
            log.fail(f"Codex run failed: run={run_id}, error={exc}")

        _send_text_message(
            lark=lark,
            client=api_client,
            create_message_request=create_message_request,
            create_message_request_body=create_message_request_body,
            receive_id_type="chat_id",
            receive_id=chat_id,
            text=_truncate_feishu_text(text),
        )
        log.ok(f"result sent: run={run_id}, chat={_short_id(chat_id)}")


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


def _format_codex_reply(response_text: str, *, result_path: Any) -> str:
    if response_text.lstrip().startswith("QUESTION:"):
        return response_text
    return f"{response_text}\n\n结果文件：`{result_path}`"


def _truncate_feishu_text(text: str) -> str:
    if len(text) <= MAX_FEISHU_TEXT:
        return text
    return text[:MAX_FEISHU_TEXT] + "\n\n...（已截断，完整内容见结果文件）"


def _short_id(value: str) -> str:
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-4:]}"


def _send_text_message(
    *,
    lark: Any,
    client: Any,
    create_message_request: Any,
    create_message_request_body: Any,
    receive_id_type: str,
    receive_id: str,
    text: str,
) -> None:
    request = (
        create_message_request.builder()
        .receive_id_type(receive_id_type)
        .request_body(
            create_message_request_body.builder()
            .receive_id(receive_id)
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .build()
        )
        .build()
    )
    response = client.im.v1.message.create(request)
    if response.success():
        return

    log_id = response.get_log_id()
    raise RuntimeError(
        "client.im.v1.message.create failed, "
        f"code={response.code}, msg={response.msg}, log_id={log_id}, "
        f"resp={_format_raw_response(lark, response)}"
    )


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
