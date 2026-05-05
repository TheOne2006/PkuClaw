"""解析聊天文本或菜单 key 中的本地控制命令。"""
from __future__ import annotations

from dataclasses import dataclass


MODE_LABELS = {
    "fast": "Fast",
    "standard": "Standard",
    "deep": "Deep",
}


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
    """把菜单 key 或聊天文本识别为本地控制命令。"""
    raw_key = (event_key or "").strip()
    key = raw_key.lower()
    if key:
        if key in {"mode:fast", "pkuclaw.mode.fast"}:
            return ControlCommand("set_mode", "fast")
        if key in {"mode:standard", "pkuclaw.mode.standard"}:
            return ControlCommand("set_mode", "standard")
        if key in {"mode:deep", "pkuclaw.mode.deep"}:
            return ControlCommand("set_mode", "deep")
        if key.startswith("model:"):
            return ControlCommand("set_model", raw_key.split(":", 1)[1].strip())
        if key.startswith("reasoning:"):
            return ControlCommand(
                "set_reasoning",
                raw_key.split(":", 1)[1].strip().lower(),
            )
        if key in {"agent:codex", "pkuclaw.agent.codex"}:
            return ControlCommand("set_provider", "codex")
        if key in {"status", "status:current", "pkuclaw.status"}:
            return ControlCommand("status")
        if key in {"runs:recent", "pkuclaw.runs.recent"}:
            return ControlCommand("recent_runs")

    normalized = text.strip().lower().replace(" ", "")
    if not normalized:
        return None

    if normalized in {"fast", "fast模式", "切换fast模式", "开启fast模式"}:
        return ControlCommand("set_mode", "fast")
    if normalized in {"standard", "标准", "标准模式", "切换标准模式"}:
        return ControlCommand("set_mode", "standard")
    if normalized in {"deep", "深度", "深度模式", "切换深度模式"}:
        return ControlCommand("set_mode", "deep")
    if normalized.startswith("模型:") or normalized.startswith("model:"):
        return ControlCommand("set_model", normalized.split(":", 1)[1].strip())
    if normalized.startswith("思考强度:") or normalized.startswith("reasoning:"):
        return ControlCommand("set_reasoning", normalized.split(":", 1)[1].strip())
    if normalized in {"状态", "查看状态", "当前状态", "查看当前状态", "当前会话设置"}:
        return ControlCommand("status")
    if normalized in {"最近任务", "查看最近任务", "列出最近任务"}:
        return ControlCommand("recent_runs")
    return None


def mode_label(mode: str) -> str:
    """把内部 mode 名称转换成用户可读标签。"""
    return MODE_LABELS.get(mode, mode)
