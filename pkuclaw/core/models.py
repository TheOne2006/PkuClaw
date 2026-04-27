from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ChannelMessage:
    channel: str
    conversation_id: str
    text: str
    sender_id: str | None = None
    event_key: str | None = None
    raw: Any | None = None


@dataclass(frozen=True)
class CoreDispatch:
    reply_text: str
    run_id: str | None = None
    plan: "TaskPlan | None" = None
    handled_locally: bool = False


@dataclass(frozen=True)
class TaskPlan:
    intent: str
    capability_names: tuple[str, ...]
    ack: str
    requires_codex: bool = True


@dataclass(frozen=True)
class WorkerResult:
    run_id: str
    status: str
    response_text: str
    session_id: str | None
    result_path: Path
