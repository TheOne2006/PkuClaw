from __future__ import annotations

from pkuclaw.core.models import TaskPlan


def classify_message(text: str) -> TaskPlan:
    """Classify natural language only enough to pick backend capabilities."""
    cleaned = text.strip()
    lowered = cleaned.lower()

    if _contains_any(lowered, ("笔记", "讲义", "notes", "note", "lecture", "继续笔记")):
        return TaskPlan(
            intent="notes",
            capability_names=("notes.write",),
            ack="收到，我会按笔记工作流启动 Codex worker。",
        )
    if _contains_any(lowered, ("作业", "homework", "hw", "习题", "提交", "解答")):
        return TaskPlan(
            intent="homework",
            capability_names=("homework.plan",),
            ack="收到，我会按作业 dry-run 工作流启动 Codex worker。",
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
            capability_names=("notice.summarize",),
            ack="收到，我会按课程通知/DDL 工作流启动 Codex worker。",
        )
    return TaskPlan(
        intent="general",
        capability_names=(),
        ack="收到，我交给 Codex worker 处理。",
    )


def route_message(text: str) -> str:
    """Compatibility helper for tests and simple handlers."""
    return classify_message(text).ack


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
