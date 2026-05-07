"""把 channel-neutral 的运行状态渲染为飞书 CardKit JSON。"""
from __future__ import annotations

import time
from typing import Any

from .schema import (
    DETAIL_PAGE_SIZE,
    MAX_CARD_TEXT,
    META_TEXT_SIZE,
    base_card,
    detail_button,
    detail_pager,
    duration_text,
    final_status_label,
    markdown_block,
    strip_markdown_noise,
)


class FeishuCardRenderer:
    """飞书运行卡、详情卡和控制卡的 JSON 渲染器。"""
    def streaming_answer_card(
        self,
        *,
        run_id: str,
        answer_text: str,
        started_at: float,
    ) -> dict[str, Any]:
        """渲染运行中的流式回答卡片。"""
        elapsed = duration_text(started_at, time.monotonic())
        return base_card(
            title="PkuClaw 正在回复",
            template="blue",
            streaming=True,
            elements=[
                markdown_block(
                    f"**运行中** · {elapsed}",
                    limit=160,
                    text_size=META_TEXT_SIZE,
                ),
                markdown_block(
                    answer_text.strip() or "正在思考...",
                    limit=MAX_CARD_TEXT,
                    strip_inline_code=False,
                ),
            ],
        )

    def final_answer_card(
        self,
        *,
        status: str,
        run_id: str,
        response_text: str,
        started_at: float,
        finished_at: float,
    ) -> dict[str, Any]:
        """渲染运行结束或失败后的最终回答卡片。"""
        needs_user = response_text.lstrip().startswith("QUESTION:")
        template = "orange" if needs_user else "green"
        title = "PkuClaw 需要你确认" if needs_user else "PkuClaw 已完成"
        if status != "succeeded":
            template = "red"
            title = "PkuClaw 处理失败"

        result = strip_markdown_noise(response_text)
        return base_card(
            title=title,
            template=template,
            streaming=False,
            elements=[
                markdown_block(
                    f"**{final_status_label(status, needs_user)}** · "
                    f"{status} · {duration_text(started_at, finished_at)}",
                    limit=180,
                    text_size=META_TEXT_SIZE,
                ),
                markdown_block(result),
                detail_button(run_id),
            ],
        )

    def run_detail_card(
        self,
        *,
        run_id: str,
        status: str,
        elapsed: str,
        agent_context: dict[str, str],
        artifacts: dict[str, str],
        events: list[str],
        page: int,
    ) -> dict[str, Any]:
        """渲染 Codex artifacts 和事件分页详情卡。"""
        total_pages = max(1, (len(events) + DETAIL_PAGE_SIZE - 1) // DETAIL_PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        start = page * DETAIL_PAGE_SIZE
        page_events = events[start : start + DETAIL_PAGE_SIZE]
        event_text = "\n".join(page_events) or "没有记录到 Codex 事件。"

        elements = [
            markdown_block(
                "**运行概览**\n"
                f"- 状态：{_run_status_label(status)}\n"
                f"- 耗时：{elapsed}\n"
                f"- Run：{run_id[:8]}\n"
                f"- 模型：{agent_context.get('model', '默认')} · "
                f"推理：{agent_context.get('reasoning', '默认')}\n"
                f"- 模式：{agent_context.get('mode', '默认')}\n"
                f"- 运行文件夹：{artifacts.get('run_dir', '无')}",
                limit=1000,
                text_size=META_TEXT_SIZE,
                strip_inline_code=False,
            ),
            markdown_block(
                f"**Codex 事件 · {page + 1}/{total_pages}**\n\n{event_text}",
                limit=MAX_CARD_TEXT,
                text_size=META_TEXT_SIZE,
                strip_inline_code=False,
            ),
        ]
        elements.extend(detail_pager(run_id=run_id, page=page, total_pages=total_pages))
        return base_card(
            title="PkuClaw 运行详情",
            template="blue" if status == "succeeded" else "red",
            streaming=False,
            elements=elements,
        )

    def control_card(
        self,
        *,
        title: str,
        body: str,
        template: str = "blue",
    ) -> dict[str, Any]:
        """渲染简单控制/状态回复卡。"""
        return base_card(
            title=title,
            template=template,
            streaming=False,
            elements=[
                markdown_block(body),
            ],
        )


def _run_status_label(status: str) -> str:
    """把 run 状态转换为详情卡里的短中文状态。"""
    labels = {
        "queued": "排队中",
        "running": "运行中",
        "succeeded": "成功",
        "failed": "失败",
        "cancelled": "已取消",
    }
    label = labels.get(status, status or "未知")
    if label == status:
        return label
    return f"{label}（{status}）"
