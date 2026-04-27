from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


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
    requires_code_agent: bool = True


@dataclass(frozen=True)
class CodeAgentSettings:
    provider: str | None = None
    mode: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class CodeAgentResult:
    run_id: str
    status: str
    response_text: str
    session_id: str | None
    result_path: Path


@dataclass(frozen=True)
class CodeAgentEvent:
    run_id: str
    kind: str
    message: str
    phase: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class CodeAgentEventSink(Protocol):
    def emit(self, event: CodeAgentEvent) -> None:
        """Receive a structured, channel-neutral code-agent event."""


def merge_agent_settings(
    defaults: CodeAgentSettings,
    overrides: CodeAgentSettings,
) -> CodeAgentSettings:
    return CodeAgentSettings(
        provider=overrides.provider or defaults.provider or "codex",
        mode=overrides.mode or defaults.mode or "standard",
        model=overrides.model or defaults.model,
        reasoning_effort=overrides.reasoning_effort or defaults.reasoning_effort,
    )
