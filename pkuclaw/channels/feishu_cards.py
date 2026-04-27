from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pkuclaw.core import logging as log
from pkuclaw.core.models import CodeAgentEvent, CodeAgentEventSink
from pkuclaw.core.store import Store


MAX_CARD_TEXT = 2500
MAX_EVENT_COUNT = 8
PATCH_INTERVAL_SECONDS = 1.0


class FeishuMessageClient:
    def __init__(
        self,
        *,
        lark: Any,
        client: Any,
        create_message_request: Any,
        create_message_request_body: Any,
        patch_message_request: Any,
        patch_message_request_body: Any,
    ) -> None:
        self.lark = lark
        self.client = client
        self.create_message_request = create_message_request
        self.create_message_request_body = create_message_request_body
        self.patch_message_request = patch_message_request
        self.patch_message_request_body = patch_message_request_body

    def send_card(
        self,
        *,
        receive_id_type: str,
        receive_id: str,
        card: dict[str, Any],
    ) -> str:
        request = (
            self.create_message_request.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                self.create_message_request_body.builder()
                .receive_id(receive_id)
                .msg_type("interactive")
                .content(_card_content(card))
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.create(request)
        self._raise_if_failed(response, "client.im.v1.message.create")
        message_id = _response_message_id(response)
        if not message_id:
            raise RuntimeError("Feishu create message response missing message_id")
        return message_id

    def patch_card(self, *, message_id: str, card: dict[str, Any]) -> None:
        request = (
            self.patch_message_request.builder()
            .message_id(message_id)
            .request_body(
                self.patch_message_request_body.builder()
                .content(_card_content(card))
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.patch(request)
        self._raise_if_failed(response, "client.im.v1.message.patch")

    def _raise_if_failed(self, response: Any, operation: str) -> None:
        if response.success():
            return
        log_id = response.get_log_id()
        raise RuntimeError(
            f"{operation} failed, code={response.code}, msg={response.msg}, "
            f"log_id={log_id}, resp={_format_raw_response(self.lark, response)}"
        )


class FeishuCardRenderer:
    def run_progress_card(
        self,
        *,
        run_id: str,
        user_text: str,
        ack: str,
        phase: str,
        events: list[str],
        agent_context: dict[str, str],
        started_at: float,
    ) -> dict[str, Any]:
        elapsed = _duration_text(started_at, time.monotonic())
        progress = "\n".join(f"- {_lark_md(item)}" for item in events) or "- 等待启动"
        return _base_card(
            title="PkuClaw 正在处理",
            template="blue",
            elements=[
                _markdown_div(
                    f"**请求**\n{_lark_md(_compact(user_text, 260))}\n\n"
                    f"**响应**\n{_lark_md(_compact(ack, 260))}"
                ),
                _fields(
                    [
                        ("Run", run_id[:12]),
                        ("阶段", phase),
                        ("Agent", agent_context.get("provider", "codex")),
                        ("模式", agent_context.get("mode", "standard")),
                        ("模型", agent_context.get("model", "默认")),
                        ("思考", agent_context.get("reasoning", "默认")),
                        ("耗时", elapsed),
                    ]
                ),
                {"tag": "hr"},
                _markdown_div(f"**实时进度**\n{_compact(progress, MAX_CARD_TEXT)}"),
                _actions(),
            ],
        )

    def final_card(
        self,
        *,
        status: str,
        run_id: str,
        user_text: str,
        response_text: str,
        result_path: Path | str | None,
        session_id: str | None,
        events: list[str],
        started_at: float,
        finished_at: float,
    ) -> dict[str, Any]:
        needs_user = response_text.lstrip().startswith("QUESTION:")
        template = "orange" if needs_user else "green"
        title = "PkuClaw 需要你确认" if needs_user else "PkuClaw 已完成"
        if status != "succeeded":
            template = "red"
            title = "PkuClaw 处理失败"

        progress = "\n".join(f"- {_lark_md(item)}" for item in events)
        result = _compact(_strip_markdown_noise(response_text), MAX_CARD_TEXT)
        return _base_card(
            title=title,
            template=template,
            elements=[
                _markdown_div(f"**请求**\n{_lark_md(_compact(user_text, 260))}"),
                _markdown_div(f"**总结**\n{_lark_md(result)}"),
                _fields(
                    [
                        ("Run", run_id[:12]),
                        ("状态", status),
                        ("耗时", _duration_text(started_at, finished_at)),
                        ("Thread", session_id or "无"),
                        ("结果文件", str(result_path or "无")),
                    ]
                ),
                {"tag": "hr"},
                _markdown_div(f"**最近事件**\n{_compact(progress, 900) or '- 无'}"),
                _actions(),
            ],
        )

    def control_card(
        self,
        *,
        title: str,
        body: str,
        template: str = "blue",
    ) -> dict[str, Any]:
        return _base_card(
            title=title,
            template=template,
            elements=[
                _markdown_div(_lark_md(_compact(body, MAX_CARD_TEXT))),
                _actions(),
            ],
        )


@dataclass
class FeishuRunCardSink(CodeAgentEventSink):
    client: FeishuMessageClient
    renderer: FeishuCardRenderer
    store: Store
    chat_id: str
    run_id: str
    user_text: str
    ack: str
    agent_context: dict[str, str]
    started_at: float = field(default_factory=time.monotonic)
    message_id: str | None = None
    phase: str = "queued"
    events: list[str] = field(default_factory=list)
    last_patch_at: float = 0.0

    def start(self) -> None:
        card = self.renderer.run_progress_card(
            run_id=self.run_id,
            user_text=self.user_text,
            ack=self.ack,
            phase=self.phase,
            events=self.events,
            agent_context=self.agent_context,
            started_at=self.started_at,
        )
        self.message_id = self.client.send_card(
            receive_id_type="chat_id",
            receive_id=self.chat_id,
            card=card,
        )
        self.store.record_channel_message(
            run_id=self.run_id,
            channel="feishu",
            target_id=self.chat_id,
            external_message_id=self.message_id,
        )
        log.ok(
            "Feishu run card sent: "
            f"run={self.run_id}, message={_short_id(self.message_id)}"
        )

    def emit(self, event: CodeAgentEvent) -> None:
        if event.kind == "final":
            self._append_event(event)
            self._patch_final(
                status=event.data.get("status", "succeeded"),
                response_text=event.message,
                result_path=event.data.get("result_path"),
                session_id=event.data.get("session_id"),
            )
            return

        if event.kind == "error":
            self._append_event(event)
            self._patch_final(
                status="failed",
                response_text=event.message,
                result_path=event.data.get("result_path"),
                session_id=event.data.get("session_id"),
            )
            return

        phase_changed = bool(event.phase and event.phase != self.phase)
        if event.phase:
            self.phase = event.phase
        self._append_event(event)
        if phase_changed or time.monotonic() - self.last_patch_at >= PATCH_INTERVAL_SECONDS:
            self._patch_progress()

    def fail(self, message: str) -> None:
        self._append_text(f"处理失败：{message}")
        self._patch_final(
            status="failed",
            response_text=message,
            result_path=None,
            session_id=None,
        )

    def _append_event(self, event: CodeAgentEvent) -> None:
        self._append_text(event.message)

    def _append_text(self, message: str) -> None:
        self.events.append(_compact(message, 220))
        del self.events[:-MAX_EVENT_COUNT]

    def _patch_progress(self) -> None:
        if not self.message_id:
            return
        card = self.renderer.run_progress_card(
            run_id=self.run_id,
            user_text=self.user_text,
            ack=self.ack,
            phase=self.phase,
            events=self.events,
            agent_context=self.agent_context,
            started_at=self.started_at,
        )
        self.client.patch_card(message_id=self.message_id, card=card)
        self.last_patch_at = time.monotonic()

    def _patch_final(
        self,
        *,
        status: str,
        response_text: str,
        result_path: str | None,
        session_id: str | None,
    ) -> None:
        if not self.message_id:
            return
        finished_at = time.monotonic()
        card = self.renderer.final_card(
            status=status,
            run_id=self.run_id,
            user_text=self.user_text,
            response_text=response_text,
            result_path=result_path,
            session_id=session_id,
            events=self.events,
            started_at=self.started_at,
            finished_at=finished_at,
        )
        self.client.patch_card(message_id=self.message_id, card=card)
        self.last_patch_at = finished_at
        log.ok(f"Feishu run card finalized: run={self.run_id}, status={status}")


def _base_card(
    *,
    title: str,
    template: str,
    elements: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "config": {
            "wide_screen_mode": True,
            "update_multi": True,
        },
        "header": {
            "template": template,
            "title": {
                "tag": "plain_text",
                "content": title,
            },
        },
        "elements": elements,
    }


def _markdown_div(content: str) -> dict[str, Any]:
    return {
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": _compact(content, MAX_CARD_TEXT),
        },
    }


def _fields(items: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "tag": "div",
        "fields": [
            {
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**{_lark_md(label)}**\n"
                        f"{_lark_md(_compact(value, 240))}"
                    ),
                },
            }
            for label, value in items
        ],
    }


def _actions() -> dict[str, Any]:
    return {
        "tag": "action",
        "actions": [
            _button("状态", "status", "default"),
            _button("最近任务", "runs:recent", "default"),
            _button("Fast", "mode:fast", "primary"),
            _button("Standard", "mode:standard", "default"),
            _button("Deep", "mode:deep", "default"),
        ],
    }


def _button(text: str, event_key: str, button_type: str) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {
            "tag": "plain_text",
            "content": text,
        },
        "type": button_type,
        "value": {
            "event_key": event_key,
        },
    }


def _card_content(card: dict[str, Any]) -> str:
    return json.dumps(card, ensure_ascii=False, separators=(",", ":"))


def _response_message_id(response: Any) -> str | None:
    data = getattr(response, "data", None)
    message_id = getattr(data, "message_id", None)
    return message_id if isinstance(message_id, str) and message_id else None


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


def _strip_markdown_noise(text: str) -> str:
    return text.replace("```", "`").strip()


def _lark_md(text: str) -> str:
    return str(text).replace("<", "＜").replace(">", "＞")


def _compact(text: str, limit: int) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _duration_text(started_at: float, finished_at: float) -> str:
    elapsed = max(0.0, finished_at - started_at)
    if elapsed < 60:
        return f"{elapsed:.1f}s"
    minutes, seconds = divmod(int(elapsed), 60)
    return f"{minutes}m{seconds:02d}s"


def _short_id(value: str) -> str:
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-4:]}"
