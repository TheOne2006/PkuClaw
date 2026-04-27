from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pkuclaw.core.store import RunRecord


@dataclass(frozen=True)
class AgentArtifactDetail:
    elapsed: str
    artifacts: dict[str, str]
    events: list[str]


def build_codex_artifact_detail(
    *,
    data_dir: Path,
    run: RunRecord,
) -> AgentArtifactDetail:
    run_dir = data_dir / "agent_runs" / "codex" / run.run_id
    prompt_path = run_dir / "prompt.md"
    stdout_path = run_dir / "stdout.jsonl"
    stderr_path = run_dir / "stderr.log"
    result_path = Path(run.result_path) if run.result_path else run_dir / "result.md"
    return AgentArtifactDetail(
        elapsed=_run_elapsed(run.created_at, run.finished_at),
        artifacts={
            "prompt": _artifact_label(prompt_path),
            "stdout": _artifact_label(stdout_path),
            "stderr": _artifact_label(stderr_path),
            "result": _artifact_label(result_path),
        },
        events=codex_trace_events(stdout_path),
    )


def codex_trace_events(stdout_path: Path) -> list[str]:
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
    if path.exists():
        return str(path)
    return f"{path} (missing)"


def _codex_trace_line(line: str) -> str:
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
    command = _find_key_recursive(data, {"command"})
    if isinstance(command, str) and command.strip():
        return f"{event_type}: command {_compact_text(command, 140)}"
    text = _find_key_recursive(data, {"delta", "text", "message", "content"})
    if isinstance(text, str) and text.strip():
        return f"{event_type}: {_compact_text(text, 160)}"
    return event_type


def _find_key_recursive(value: Any, keys: set[str]) -> Any:
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
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _run_elapsed(created_at: str, finished_at: str | None) -> str:
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
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp
