"""轻量意图分类器，用于选择默认 sub-skill 工作流。"""
from __future__ import annotations

from pkuclaw.core.models import TaskPlan


def classify_message(text: str) -> TaskPlan:
    """Classify natural language only enough to pick PkuClaw sub-skills."""
    cleaned = text.strip()
    lowered = cleaned.lower()

    if _contains_any(lowered, ("笔记", "讲义", "notes", "note", "lecture", "继续笔记")):
        return TaskPlan(
            intent="notes",
            skill_names=("tasks/write-notes.md",),
            ack="收到，我会按笔记工作流启动 Code Agent。",
        )
    if _contains_any(lowered, ("作业", "homework", "hw", "习题", "提交", "解答")):
        return TaskPlan(
            intent="homework",
            skill_names=("tasks/do-homework.md",),
            ack="收到，我会按作业 dry-run 工作流启动 Code Agent。",
        )
    if _contains_any(
        lowered,
        (
            "同步",
            "通知",
            "ddl",
            "deadline",
            "截止",
            "这周",
            "本周",
            "有什么事",
            "要交",
        ),
    ):
        return TaskPlan(
            intent="sync",
            skill_names=("tasks/sync-notices.md",),
            ack="收到，我会按课程通知/DDL 工作流启动 Code Agent。",
        )
    return TaskPlan(
        intent="general",
        skill_names=(),
        ack="收到，我交给 Code Agent 处理。",
    )


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    """判断文本是否包含任一候选关键词。"""
    return any(needle in text for needle in needles)
