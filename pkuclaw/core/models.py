"""Shared data models for CoreRuntime, AgentWrapper, and channels."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pkuclaw.channels.base import ChannelTarget


DEFAULT_AGENT_PROVIDER = "codex"
DEFAULT_AGENT_MODE = "fixed"
DEFAULT_AGENT_MODEL = "gpt-5.5"
DEFAULT_AGENT_REASONING_EFFORT = "xhigh"
RUN_SOURCES = ("realtime", "loop")


@dataclass(frozen=True)
class CoreDispatch:
    """CoreRuntime dispatch result for one channel or loop input."""

    reply_text: str
    run_id: str | None = None
    plan: "TaskPlan | None" = None
    agent_request: "AgentRunRequest | None" = None
    channel_target: ChannelTarget | None = None
    handled_locally: bool = False


@dataclass(frozen=True)
class TaskPlan:
    """Fixed per-run suggested skills and acknowledgement text."""

    suggested_skills: tuple[str, ...]
    ack: str
    requires_agent: bool = True


@dataclass(frozen=True)
class AgentSettings:
    """Agent provider, mode, model and reasoning overrides."""

    provider: str | None = None
    mode: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class AgentRunRequest:
    """Normalized request handed from CoreRuntime to AgentWrapper."""

    source: str
    conversation_id: str
    text: str
    suggested_skills: tuple[str, ...]
    channel: str | None = None
    sender_id: str | None = None
    channel_context: dict[str, Any] = field(default_factory=dict)
    sink_mode: str = "streaming"

    def __post_init__(self) -> None:
        if self.source not in RUN_SOURCES:
            raise RuntimeError(
                f"unsupported agent run source: {self.source}; "
                f"expected one of {', '.join(RUN_SOURCES)}"
            )


@dataclass(frozen=True)
class AgentResult:
    """Unified result returned by a concrete Agent provider."""

    run_id: str
    status: str
    response_text: str
    session_id: str | None
    result_path: Path
    error: str | None = None


@dataclass(frozen=True)
class AgentEvent:
    """Structured event emitted by provider execution to channel sinks."""

    run_id: str
    kind: str
    message: str
    phase: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class AgentEventSink(Protocol):
    """Channel-neutral sink for provider events."""

    def emit(self, event: AgentEvent) -> None:
        """Receive a structured provider event."""


def merge_agent_settings(
    defaults: AgentSettings,
    overrides: AgentSettings,
) -> AgentSettings:
    """Merge conversation overrides over runtime defaults."""

    return AgentSettings(
        provider=overrides.provider or defaults.provider or DEFAULT_AGENT_PROVIDER,
        mode=overrides.mode or defaults.mode or DEFAULT_AGENT_MODE,
        model=overrides.model or defaults.model or DEFAULT_AGENT_MODEL,
        reasoning_effort=(
            overrides.reasoning_effort
            or defaults.reasoning_effort
            or DEFAULT_AGENT_REASONING_EFFORT
        ),
    )
