"""把 AgentEvent 流式渲染到同一张飞书运行卡片。"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from pkuclaw.channels.base import ChannelTarget
from pkuclaw.core import logging as log
from pkuclaw.core.models import AgentEvent, AgentEventSink
from pkuclaw.core.store import Store

from ..ids import short_id
from .client import FeishuCardKitClient
from .renderer import FeishuCardRenderer


STREAM_UPDATE_INTERVAL_SECONDS = 0.5
HEARTBEAT_INTERVAL_SECONDS = 1.0


@dataclass
class FeishuRunCardSink(AgentEventSink):
    """实时收集 AgentEvent，并节流更新一张飞书卡片。"""
    client: FeishuCardKitClient
    renderer: FeishuCardRenderer
    store: Store
    target: ChannelTarget
    run_id: str
    started_at: float = field(default_factory=time.monotonic)
    message_id: str | None = None
    card_id: str | None = None
    update_sequence: int = 0
    status: str = "running"
    answer_text: str = ""
    last_update_at: float = 0.0
    heartbeat_stop_event: threading.Event = field(default_factory=threading.Event)
    update_lock: threading.Lock = field(default_factory=threading.Lock)
    heartbeat_thread: threading.Thread | None = None

    def start(self) -> None:
        """启动对应 runtime/channel 组件。"""
        card = self.renderer.streaming_answer_card(
            run_id=self.run_id,
            answer_text=self.answer_text,
            started_at=self.started_at,
        )
        sent_card = self.client.send_card(
            receive_id_type=self.target.target_type,
            receive_id=self.target.target_id,
            card=card,
        )
        self.message_id = sent_card.message_id
        self.card_id = sent_card.card_id
        self.store.record_channel_message(
            run_id=self.run_id,
            channel=self.target.channel,
            target_id=self.target.target_id,
            external_message_id=self.message_id,
        )
        log.ok(
            "Feishu run card sent: "
            f"run={self.run_id}, message={short_id(self.message_id)}, "
            f"card={short_id(self.card_id)}"
        )
        self._start_heartbeat()

    def emit(self, event: AgentEvent) -> None:
        """接收 provider 事件，并根据事件类型更新流式或最终卡片。"""
        # Final/error events replace the streaming card exactly once; output
        # events are accumulated and throttled to avoid Feishu rate pressure.
        if event.kind == "final":
            self.answer_text = event.message
            self._update_final(
                status=event.data.get("status", "succeeded"),
                response_text=event.message,
            )
            return

        if event.kind == "error":
            self.answer_text = event.message
            self._update_final(
                status="failed",
                response_text=event.message,
            )
            return

        if event.kind == "output":
            self._append_answer(event)
            self._update_streaming()

    def fail(self, message: str) -> None:
        """把当前 sink 置为失败态并展示错误。"""
        self.answer_text = message
        self._update_final(
            status="failed",
            response_text=message,
        )

    def _append_answer(self, event: AgentEvent) -> None:
        """兼容 Codex delta 和整段输出事件，累积用户可见答案文本。"""
        codex_type = str(event.data.get("codex_type") or "").lower()
        if "delta" in codex_type:
            # Delta events preserve whitespace and are appended directly.
            if not event.message:
                return
            self.answer_text = f"{self.answer_text}{event.message}"
            return
        text = event.message.strip()
        if not text:
            return
        if not self.answer_text:
            self.answer_text = text
            return
        separator = "" if self.answer_text.endswith(("\n", " ")) else "\n"
        self.answer_text = f"{self.answer_text}{separator}{text}"

    def _update_streaming(self, *, force: bool = False) -> None:
        """按节流策略刷新运行中的飞书卡片。"""
        if not self.card_id:
            return
        now = time.monotonic()
        # Normal streaming updates are rate-limited; heartbeat calls pass
        # force=True so long-running silent phases still show elapsed time.
        if not force and now - self.last_update_at < STREAM_UPDATE_INTERVAL_SECONDS:
            return
        card = self.renderer.streaming_answer_card(
            run_id=self.run_id,
            answer_text=self.answer_text,
            started_at=self.started_at,
        )
        self._update_card(card=card, updated_at=now)

    def _update_final(
        self,
        *,
        status: str,
        response_text: str,
    ) -> None:
        """停止心跳并把飞书卡片更新为最终状态。"""
        if not self.card_id:
            return
        self.status = status
        self._stop_heartbeat()
        finished_at = time.monotonic()
        card = self.renderer.final_answer_card(
            status=status,
            run_id=self.run_id,
            response_text=response_text,
            started_at=self.started_at,
            finished_at=finished_at,
        )
        self._update_card(card=card, updated_at=finished_at)
        log.ok(
            "Feishu run card finalized: "
            f"run={self.run_id}, status={status}, card={short_id(self.card_id)}"
        )

    def _update_card(self, *, card: dict[str, Any], updated_at: float) -> None:
        """串行调用飞书 update_card 并记录最近更新时间。"""
        if not self.card_id:
            return
        with self.update_lock:
            self.client.update_card(
                card_id=self.card_id,
                card=card,
                sequence=self._next_sequence(),
            )
            self.last_update_at = updated_at

    def _start_heartbeat(self) -> None:
        """启动后台心跳线程，避免长时间无输出时卡片停在旧状态。"""
        def beat() -> None:
            """心跳线程入口，周期性强制刷新 streaming 卡片。"""
            while not self.heartbeat_stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
                self._update_streaming(force=True)

        self.heartbeat_thread = threading.Thread(
            target=beat,
            name=f"feishu-card-heartbeat-{self.run_id[:8]}",
            daemon=True,
        )
        self.heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        """停止心跳线程并短暂等待退出。"""
        self.heartbeat_stop_event.set()
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=1)

    def _next_sequence(self) -> int:
        """递增并返回飞书卡片更新 sequence。"""
        self.update_sequence += 1
        return self.update_sequence


@dataclass(frozen=True)
class FeishuRunCardSinkFactory:
    """为 realtime run 创建飞书卡片 sink 的工厂。"""
    client: FeishuCardKitClient
    renderer: FeishuCardRenderer

    def create_realtime_sink(
        self,
        *,
        target: ChannelTarget,
        run_id: str,
        store: Store,
    ) -> FeishuRunCardSink:
        """为 realtime run 创建 channel-specific AgentEvent sink。"""
        if target.channel != "feishu":
            raise RuntimeError(
                f"Feishu sink received non-Feishu target: {target.channel}"
            )
        return FeishuRunCardSink(
            client=self.client,
            renderer=self.renderer,
            store=store,
            target=target,
            run_id=run_id,
        )
