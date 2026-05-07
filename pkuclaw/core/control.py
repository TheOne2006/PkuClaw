"""预留聊天文本/菜单 key 到本地控制命令的解析入口。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ControlCommand:
    """本地控制命令的规范化表示。"""
    kind: str
    value: str | None = None


def parse_control_command(
    *,
    text: str = "",
    event_key: str | None = None,
) -> ControlCommand | None:
    """把菜单 key 或聊天文本识别为本地控制命令。

    旧的 `mode:fast` / `model:<name>` / `reasoning:<value>` 等具体命令已清空。
    这里保留函数和 `ControlCommand` 数据结构，方便后续重新设计飞书菜单 key 时
    直接接回 `CoreRuntime.ingest_channel_message`。
    """
    _ = text, event_key
    return None


def mode_label(mode: str) -> str:
    """保留 mode 展示入口；当前 mode 不再驱动 reasoning preset。"""
    return mode
