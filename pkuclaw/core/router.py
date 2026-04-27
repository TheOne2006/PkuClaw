from __future__ import annotations


def route_message(text: str) -> str:
    """Temporary chat router until course state and Codex workers are wired."""
    cleaned = text.strip()
    if cleaned in {"/help", "help", "帮助"}:
        return "可用命令：/status, /sync, /ddl, /notes 课程名"
    if cleaned in {"/status", "status", "今天有什么 ddl？", "今天有什么ddl"}:
        return "课程状态库还未初始化。下一步会接入 pku3b 扫描。"
    if cleaned in {"/sync", "sync", "同步"}:
        return "同步任务骨架已创建，collector 实现待接入。"
    return f"收到：{cleaned}"
