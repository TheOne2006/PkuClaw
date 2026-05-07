"""读取 Codex run 产物并整理为可展示的详情摘要。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pkuclaw.core.store import RunRecord


_CODEX_EVENT_LABELS = {
    "session_configured": "会话已配置",
    "thread.started": "线程开始",
    "turn.started": "回合开始",
    "turn.completed": "回合完成",
    "item.started": "步骤开始",
    "item.completed": "步骤完成",
    "item.failed": "步骤失败",
}


@dataclass(frozen=True)
class AgentArtifactDetail:
    """运行详情卡所需的耗时、产物路径和 Codex 事件摘要。"""
    elapsed: str
    artifacts: dict[str, str]
    events: list[str]


def build_codex_artifact_detail(
    *,
    data_dir: Path,
    run: RunRecord,
) -> AgentArtifactDetail:
    """根据 run 记录定位 Codex artifacts 并生成详情摘要。"""
    run_dir = data_dir / "agent_runs" / "codex" / run.run_id
    prompt_path = run_dir / "prompt.md"
    stdout_path = run_dir / "stdout.jsonl"
    stderr_path = run_dir / "stderr.log"
    result_path = Path(run.result_path) if run.result_path else run_dir / "result.md"
    return AgentArtifactDetail(
        elapsed=_run_elapsed(run.created_at, run.finished_at),
        artifacts={
            "run_dir": _artifact_label(run_dir),
            "prompt": _artifact_label(prompt_path),
            "stdout": _artifact_label(stdout_path),
            "stderr": _artifact_label(stderr_path),
            "result": _artifact_label(result_path),
        },
        events=codex_trace_events(stdout_path),
    )


def codex_trace_events(stdout_path: Path) -> list[str]:
    """读取 stdout.jsonl 并把 Codex 事件压缩成详情卡文本。"""
    if not stdout_path.exists():
        return ["stdout.jsonl 尚未生成。"]

    events: list[str] = []
    for index, line in enumerate(
        stdout_path.read_text(encoding="utf-8", errors="replace").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        events.append(f"{index}. {_codex_trace_line(line)}")
    return events or ["stdout.jsonl 为空。"]


def _artifact_label(path: Path) -> str:
    """返回 artifact 路径或 missing 标记。"""
    if path.exists():
        return str(path)
    return f"{path} (missing)"


def _codex_trace_line(line: str) -> str:
    """把一行 Codex JSONL 压缩成人类可读事件。"""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return _compact_text(line, 180)
    if not isinstance(data, dict):
        return _compact_text(line, 180)

    event_type = str(
        data.get("type")
        or data.get("event")
        or data.get("kind")
        or "codex_event"
    )
    label = _codex_event_label(event_type)
    command = _find_key_recursive(data, {"command"})
    if isinstance(command, str) and command.strip():
        return f"{label}：命令 {_compact_text(command, 180)}"
    text = _find_key_recursive(data, {"delta", "text", "message", "content"})
    if isinstance(text, str) and text.strip():
        return f"{label}：{_compact_text(text, 120)}"
    return label


def _codex_event_label(event_type: str) -> str:
    """把 Codex JSONL event type 映射为详情卡里的短文本。"""
    return _CODEX_EVENT_LABELS.get(event_type, event_type or "Codex 事件")


def _find_key_recursive(value: Any, keys: set[str]) -> Any:
    """在嵌套 dict/list 中深度查找任一候选键。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys:
                return item
            found = _find_key_recursive(item, keys)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_key_recursive(item, keys)
            if found is not None:
                return found
    return None


def _compact_text(text: str, limit: int) -> str:
    """压缩空白并按长度截断文本。"""
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _run_elapsed(created_at: str, finished_at: str | None) -> str:
    """根据 run 创建/结束时间计算展示用耗时。"""
    started = _parse_timestamp(created_at)
    finished = (
        _parse_timestamp(finished_at)
        if finished_at
        else datetime.now(timezone.utc)
    )
    if started is None:
        return "未知"
    if finished is None:
        finished = datetime.now(timezone.utc)
    elapsed = max(0.0, (finished - started).total_seconds())
    if elapsed < 60:
        return f"{elapsed:.1f}s"
    minutes, seconds = divmod(int(elapsed), 60)
    return f"{minutes}m{seconds:02d}s"


def _parse_timestamp(value: str | None) -> datetime | None:
    """安全解析 ISO8601 时间戳，并补齐 UTC timezone。"""
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp
