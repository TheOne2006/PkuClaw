"""飞书日志用的短 ID 辅助函数。"""
from __future__ import annotations


def short_id(value: str) -> str:
    """缩短外部 ID，便于在日志中低敏展示。"""
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-4:]}"
