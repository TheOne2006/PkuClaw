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
    agent_request: "AgentRunRequest | None" = None
    handled_locally: bool = False


@dataclass(frozen=True)
class TaskPlan:
    intent: str
    skill_names: tuple[str, ...]
    ack: str
    requires_agent: bool = True


@dataclass(frozen=True)
class AgentSettings:
    provider: str | None = None
    mode: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class AgentRunRequest:
    source: str
    conversation_id: str
    text: str
    intent: str
    skill_names: tuple[str, ...]
    channel: str | None = None
    sender_id: str | None = None
    channel_context: dict[str, Any] = field(default_factory=dict)
    sink_mode: str = "streaming"


@dataclass(frozen=True)
class AgentResult:
    run_id: str
    status: str
    response_text: str
    session_id: str | None
    result_path: Path
    error: str | None = None


@dataclass(frozen=True)
class AgentEvent:
    run_id: str
    kind: str
    message: str
    phase: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class AgentEventSink(Protocol):
    def emit(self, event: AgentEvent) -> None:
        """Receive a structured, channel-neutral agent event."""


def merge_agent_settings(
    defaults: AgentSettings,
    overrides: AgentSettings,
) -> AgentSettings:
    return AgentSettings(
        provider=overrides.provider or defaults.provider or "codex",
        mode=overrides.mode or defaults.mode or "standard",
        model=overrides.model or defaults.model,
        reasoning_effort=overrides.reasoning_effort or defaults.reasoning_effort,
    )
