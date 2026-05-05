"""飞书 CardKit JSON 的小型构建器和 Markdown 清洗工具。"""
from __future__ import annotations

import re
from typing import Any


MAX_CARD_TEXT = 2500
BODY_TEXT_SIZE = "pkuclaw-body"
META_TEXT_SIZE = "pkuclaw-meta"
SECTION_TEXT_SIZE = "pkuclaw-section"
DETAIL_PAGE_SIZE = 40


def base_card(
    *,
    title: str,
    template: str,
    streaming: bool,
    elements: list[dict[str, Any]],
) -> dict[str, Any]:
    """构建飞书 CardKit 2.0 的基础卡片结构。"""
    return {
        "schema": "2.0",
        "config": {
            "wide_screen_mode": True,
            "update_multi": True,
            "streaming_mode": streaming,
            "style": {
                "text_size": {
                    BODY_TEXT_SIZE: {
                        "default": "normal",
                        "pc": "normal",
                        "mobile": "large",
                    },
                    META_TEXT_SIZE: {
                        "default": "normal",
                        "pc": "notation",
                        "mobile": "normal",
                    },
                    SECTION_TEXT_SIZE: {
                        "default": "heading-3",
                        "pc": "heading",
                        "mobile": "heading-3",
                    },
                },
            },
            "summary": {
                "content": title,
            },
        },
        "header": {
            "template": template,
            "title": {
                "tag": "plain_text",
                "content": title,
            },
        },
        "body": {
            "direction": "vertical",
            "padding": "16px 14px 14px 14px",
            "vertical_spacing": "12px",
            "elements": elements,
        },
    }


def markdown_block(
    content: str,
    *,
    limit: int = MAX_CARD_TEXT,
    text_size: str = BODY_TEXT_SIZE,
    strip_inline_code: bool = True,
) -> dict[str, Any]:
    """构建一个飞书 markdown 元素，并执行清洗和截断。"""
    return {
        "tag": "markdown",
        "content": _to_card_markdown(
            content,
            limit,
            strip_inline_code=strip_inline_code,
        ),
        "text_align": "left",
        "text_size": text_size,
    }


def section_title(content: str) -> dict[str, Any]:
    """构建卡片中的小节标题。"""
    return markdown_block(
        f"**{content}**",
        limit=80,
        text_size=SECTION_TEXT_SIZE,
    )


def metadata_block(items: list[tuple[str, str]]) -> dict[str, Any]:
    """把键值对压缩成一行元信息 markdown。"""
    parts = [f"**{label}** {_inline(value, 160)}" for label, value in items]
    return markdown_block("  ·  ".join(parts), limit=900, text_size=META_TEXT_SIZE)


def detail_button(run_id: str) -> dict[str, Any]:
    """构建打开运行详情的卡片按钮。"""
    return button(
        text="查看运行详情",
        value={"action": "show_run_details", "run_id": run_id, "page": 0},
    )


def detail_pager(*, run_id: str, page: int, total_pages: int) -> list[dict[str, Any]]:
    """根据分页状态构建上一页/下一页按钮。"""
    buttons: list[dict[str, Any]] = []
    if page > 0:
        buttons.append(
            button(
                text="上一页",
                value={"action": "detail_page", "run_id": run_id, "page": page - 1},
            )
        )
    if page + 1 < total_pages:
        buttons.append(
            button(
                text="下一页",
                value={"action": "detail_page", "run_id": run_id, "page": page + 1},
                button_type="primary",
            )
        )
    if buttons:
        return buttons
    return [markdown_block("已显示全部运行事件。", limit=80, text_size=META_TEXT_SIZE)]


def button(
    *,
    text: str,
    value: dict[str, Any],
    button_type: str = "default",
) -> dict[str, Any]:
    """构建带 callback value 的飞书按钮元素。"""
    return {
        "tag": "button",
        "text": {
            "tag": "plain_text",
            "content": text,
        },
        "type": button_type,
        "behaviors": [
            {
                "type": "callback",
                "value": value,
            }
        ],
    }


def final_status_label(status: str, needs_user: bool) -> str:
    """把 run 状态转换为卡片标题中的中文状态。"""
    if status != "succeeded":
        return "失败"
    if needs_user:
        return "需要确认"
    return "已完成"


def strip_markdown_noise(text: str) -> str:
    """清理最终答案中不适合卡片展示的 Markdown 噪声。"""
    return text.strip()


def duration_text(started_at: float, finished_at: float) -> str:
    """把 monotonic 时间差格式化成短耗时文本。"""
    elapsed = max(0.0, finished_at - started_at)
    if elapsed < 60:
        return f"{elapsed:.1f}s"
    minutes, seconds = divmod(int(elapsed), 60)
    return f"{minutes}m{seconds:02d}s"


def _lark_md(text: str) -> str:
    """转义飞书 markdown 中可能被误解析的特殊标签。"""
    return re.sub(
        r"<(/?\s*(?:at|person|local_datetime|audio|link|font|text_tag|number_tag)\b)",
        r"＜\1",
        str(text),
        flags=re.IGNORECASE,
    )


def _inline(text: str, limit: int) -> str:
    """把文本压成单行并截断，适合元信息展示。"""
    return _truncate(" ".join(str(text).split()), limit)


def _to_card_markdown(text: str, limit: int, *, strip_inline_code: bool) -> str:
    """执行 Markdown 规范化、飞书标签转义和长度限制。"""
    normalized = _normalize_markdown(
        text,
        strip_inline_code=strip_inline_code,
    )
    return _truncate(_lark_md(normalized), limit)


def _normalize_markdown(text: str, *, strip_inline_code: bool) -> str:
    """按行清理 Markdown，保留代码块状态。"""
    lines: list[str] = []
    in_code_block = False
    for raw_line in str(text).replace("\r\n", "\n").split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            lines.append(_normalize_code_fence(stripped))
            continue
        if strip_inline_code and not in_code_block:
            line = _strip_inline_code(line)
        lines.append(line)
    return _collapse_blank_lines("\n".join(lines)).strip()


def _strip_inline_code(line: str) -> str:
    """移除单行中的反引号 inline code 标记。"""
    return re.sub(r"`([^`\n]+)`", r"\1", line)


def _normalize_code_fence(line: str) -> str:
    """把常见代码块语言别名转换为飞书更稳定的名称。"""
    aliases = {
        "js": "javascript",
        "py": "python",
        "sh": "shell",
        "ts": "typescript",
    }
    language = line[3:].strip().lower()
    if not language:
        return "```"
    return f"```{aliases.get(language, language)}"


def _collapse_blank_lines(text: str) -> str:
    """折叠过多空行，避免卡片占用过高。"""
    return re.sub(r"\n{3,}", "\n\n", text)


def _truncate(text: str, limit: int) -> str:
    """按字符数截断文本并追加省略号。"""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."
