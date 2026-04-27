from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

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
    client: FeishuCardKitClient
    renderer: FeishuCardRenderer
    store: Store
    chat_id: str
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
        card = self.renderer.streaming_answer_card(
            run_id=self.run_id,
            answer_text=self.answer_text,
            started_at=self.started_at,
        )
        sent_card = self.client.send_card(
            receive_id_type="chat_id",
            receive_id=self.chat_id,
            card=card,
        )
        self.message_id = sent_card.message_id
        self.card_id = sent_card.card_id
        self.store.record_channel_message(
            run_id=self.run_id,
            channel="feishu",
            target_id=self.chat_id,
            external_message_id=self.message_id,
        )
        log.ok(
            "Feishu run card sent: "
            f"run={self.run_id}, message={short_id(self.message_id)}, "
            f"card={short_id(self.card_id)}"
        )
        self._start_heartbeat()

    def emit(self, event: AgentEvent) -> None:
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
        self.answer_text = message
        self._update_final(
            status="failed",
            response_text=message,
        )

    def _append_answer(self, event: AgentEvent) -> None:
        codex_type = str(event.data.get("codex_type") or "").lower()
        if "delta" in codex_type:
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
        if not self.card_id:
            return
        now = time.monotonic()
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
        def beat() -> None:
            while not self.heartbeat_stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
                self._update_streaming(force=True)

        self.heartbeat_thread = threading.Thread(
            target=beat,
            name=f"feishu-card-heartbeat-{self.run_id[:8]}",
            daemon=True,
        )
        self.heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self.heartbeat_stop_event.set()
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=1)

    def _next_sequence(self) -> int:
        self.update_sequence += 1
        return self.update_sequence
