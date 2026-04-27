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
    metadata_block,
    section_title,
    strip_markdown_noise,
)


class FeishuCardRenderer:
    def streaming_answer_card(
        self,
        *,
        run_id: str,
        answer_text: str,
        started_at: float,
    ) -> dict[str, Any]:
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
        total_pages = max(1, (len(events) + DETAIL_PAGE_SIZE - 1) // DETAIL_PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        start = page * DETAIL_PAGE_SIZE
        page_events = events[start : start + DETAIL_PAGE_SIZE]
        event_text = "\n".join(page_events) or "没有记录到 Codex 事件。"

        elements = [
            section_title("运行详情"),
            metadata_block(
                [
                    ("状态", status),
                    ("耗时", elapsed),
                    ("Run", run_id[:8]),
                    ("模式", agent_context.get("mode", "默认")),
                    ("模型", agent_context.get("model", "默认")),
                    ("推理", agent_context.get("reasoning", "默认")),
                ]
            ),
            markdown_block(
                "**Artifacts**\n\n"
                f"- prompt: {artifacts.get('prompt', '无')}\n"
                f"- stdout: {artifacts.get('stdout', '无')}\n"
                f"- stderr: {artifacts.get('stderr', '无')}\n"
                f"- result: {artifacts.get('result', '无')}",
                limit=900,
                text_size=META_TEXT_SIZE,
            ),
            markdown_block(
                f"**Codex events · {page + 1}/{total_pages}**\n\n{event_text}",
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
        return base_card(
            title=title,
            template=template,
            streaming=False,
            elements=[
                markdown_block(body),
            ],
        )
