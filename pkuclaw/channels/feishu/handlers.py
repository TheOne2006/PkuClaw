"""飞书事件回调处理器：消息、菜单、卡片按钮和 Agent run 启动。"""
from __future__ import annotations

import threading
from concurrent.futures import Executor
from dataclasses import dataclass, field
from typing import Any

from pkuclaw.channels.base import ChannelInboundMessage, ChannelTarget
from pkuclaw.config import Settings
from pkuclaw.core import logging as log
from pkuclaw.core.app import CoreRuntime

from .cards import (
    FeishuCardKitClient,
    FeishuCardRenderer,
    FeishuRunCardSink,
    FeishuRunCardSinkFactory,
)
from .detail import send_run_detail_card
from .events import (
    card_action_operator_open_id,
    card_action_target,
    card_action_toast,
    card_action_value,
    extract_sender_open_id,
    extract_text_content,
    feishu_conversation_id,
    int_value,
    receive_id_type_for_target,
)
from .ids import short_id


@dataclass
class ChatLocks:
    """按飞书 chat_id 维护串行化锁，避免同一聊天内并发刷卡。"""
    locks: dict[str, threading.Lock] = field(default_factory=dict)
    guard: threading.Lock = field(default_factory=threading.Lock)

    def for_chat(self, chat_id: str) -> threading.Lock:
        """执行 for chat 逻辑。"""
        with self.guard:
            if chat_id not in self.locks:
                self.locks[chat_id] = threading.Lock()
            return self.locks[chat_id]


@dataclass
class FeishuEventHandlers:
    """飞书 SDK 回调对象，负责把平台事件转入 CoreRuntime。"""
    settings: Settings
    core_runtime: CoreRuntime
    message_client: FeishuCardKitClient
    card_renderer: FeishuCardRenderer
    card_action_response_cls: Any
    executor: Executor
    callback_executor: Executor
    chat_locks: ChatLocks = field(default_factory=ChatLocks)

    def on_message(self, data: Any) -> None:
        """处理飞书文本消息，分流本地控制命令或启动 realtime Agent run。"""
        event = getattr(data, "event", None)
        message = getattr(event, "message", None)
        if message is None or getattr(message, "message_type", None) != "text":
            return

        chat_id = getattr(message, "chat_id", None)
        sender_id = extract_sender_open_id(event)
        if not chat_id or not sender_id:
            return

        text = extract_text_content(getattr(message, "content", ""))
        target = ChannelTarget(
            channel="feishu",
            target_type="chat_id",
            target_id=chat_id,
        )
        envelope = ChannelInboundMessage(
            channel="feishu",
            conversation_id=feishu_conversation_id(sender_id),
            sender_id=sender_id,
            target=target,
            text=text,
            external_message_id=getattr(message, "message_id", None),
            raw=data,
        )
        dispatch = self.core_runtime.ingest_channel_message(envelope)
        log.event(
            "message received: "
            f"chat={short_id(chat_id)}, sender={short_id(sender_id)}, "
            f"run={dispatch.run_id or 'local'}, chars={len(text)}, "
            f"local={dispatch.handled_locally}"
        )
        if dispatch.run_id is None or dispatch.plan is None:
            reply_target = dispatch.channel_target or target
            # Local controls (mode/status/recent runs) still go through
            # CoreRuntime's outbox, so the Feishu adapter does not own a
            # parallel send path.
            self.core_runtime.send_channel_text(
                channel=reply_target.channel,
                target_type=reply_target.target_type,
                target_id=reply_target.target_id,
                text=dispatch.reply_text,
            )
            log.ok("local control card sent")
            return
        if dispatch.agent_request is None:
            raise RuntimeError("agent request is missing for realtime run")
        if dispatch.channel_target is None:
            raise RuntimeError("channel target is missing for realtime run")

        sink = FeishuRunCardSinkFactory(
            client=self.message_client,
            renderer=self.card_renderer,
        ).create_realtime_sink(
            target=dispatch.channel_target,
            run_id=dispatch.run_id,
            store=self.core_runtime.store,
        )
        try:
            sink.start()
        except Exception as exc:
            # If the user-facing card cannot be created, mark the queued run
            # failed before re-raising so Store state never remains "queued".
            self.core_runtime.store.mark_run_failed(dispatch.run_id, str(exc))
            log.fail(
                "failed to create Feishu run card: "
                f"run={dispatch.run_id}, error={exc}"
            )
            raise

        self.executor.submit(
            process_code_agent_run,
            self.core_runtime,
            # Per-chat lock serializes Agent runs for the same Feishu chat so
            # streaming cards are easier to follow and resource use is bounded.
            self.chat_locks.for_chat(dispatch.channel_target.target_id),
            dispatch.channel_target.target_id,
            dispatch.run_id,
            dispatch.plan,
            dispatch.agent_request,
            sink,
        )

    def on_bot_menu(self, data: Any) -> None:
        """处理飞书机器人菜单事件，并把结果以控制卡返回。"""
        event = getattr(data, "event", None)
        event_key = getattr(event, "event_key", None)
        operator = getattr(event, "operator", None)
        operator_id = getattr(operator, "operator_id", None)
        open_id = getattr(operator_id, "open_id", None)
        if not event_key or not open_id:
            log.warn("bot menu event missing event_key/open_id")
            return

        target = ChannelTarget(
            channel="feishu",
            target_type="open_id",
            target_id=open_id,
        )
        dispatch = self.core_runtime.ingest_channel_message(
            ChannelInboundMessage(
                channel="feishu",
                conversation_id=feishu_conversation_id(open_id),
                sender_id=open_id,
                target=target,
                text="",
                event_key=event_key,
                raw=data,
            )
        )
        log.event(
            "menu event received: "
            f"sender={short_id(open_id)}, key={event_key}, "
            f"local={dispatch.handled_locally}"
        )
        reply_target = dispatch.channel_target or target
        self.core_runtime.send_channel_text(
            channel=reply_target.channel,
            target_type=reply_target.target_type,
            target_id=reply_target.target_id,
            text=dispatch.reply_text,
        )
        log.ok(f"menu card sent: key={event_key}, sender={short_id(open_id)}")

    def on_card_action(self, data: Any) -> Any:
        """处理运行详情翻页等飞书卡片按钮回调。"""
        event = getattr(data, "event", None)
        value = card_action_value(event)
        action = str(value.get("action") or "")
        operator_id = card_action_operator_open_id(event)
        target_id = card_action_target(event, operator_id)
        receive_id_type = receive_id_type_for_target(target_id)
        if action not in {"show_run_details", "detail_page"}:
            log.warn(f"unsupported card action: {action or 'empty'}")
            return self._toast(
                toast_type="warning",
                content="这个按钮暂时不支持。",
            )

        run_id = str(value.get("run_id") or "")
        page = int_value(value.get("page"), default=0)
        if not run_id or not target_id:
            log.warn("card action missing run_id or target id")
            return self._toast(
                toast_type="error",
                content="没有找到这次运行。",
            )

        log.event(
            "card action received: "
            f"action={action}, run={run_id}, page={page}, "
            f"target={receive_id_type}:{short_id(target_id)}"
        )
        self.callback_executor.submit(
            send_run_detail_card,
            self.settings,
            self.core_runtime,
            self.card_renderer,
            self.message_client,
            receive_id_type,
            target_id,
            run_id,
            page,
        )
        return self._toast(
            toast_type="success",
            content="正在发送运行详情。",
        )

    def _toast(self, *, toast_type: str, content: str) -> Any:
        """构造飞书卡片按钮回调 toast。"""
        return card_action_toast(
            self.card_action_response_cls,
            toast_type=toast_type,
            content=content,
        )


def process_code_agent_run(
    core_runtime: CoreRuntime,
    lock: threading.Lock,
    chat_id: str,
    run_id: str,
    plan: Any,
    agent_request: Any,
    sink: FeishuRunCardSink,
) -> None:
    """执行 process code agent run 逻辑。"""
    with lock:
        try:
            log.stage(
                f"Agent run starting: run={run_id}, chat={short_id(chat_id)}"
            )
            result = core_runtime.run_agent(run_id, plan, agent_request, sink)
            log.ok(
                "Agent run completed: "
                f"run={run_id}, status={result.status}, "
                f"thread={result.session_id or 'none'}, result={result.result_path}"
            )
        except Exception as exc:
            core_runtime.store.mark_run_failed(run_id, str(exc))
            sink.fail(str(exc))
            log.fail(f"Agent run failed: run={run_id}, error={exc}")
