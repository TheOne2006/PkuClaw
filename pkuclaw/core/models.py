"""CoreRuntime、AgentWrapper 和 channel 之间共享的数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pkuclaw.channels.base import ChannelTarget


@dataclass(frozen=True)
class CoreDispatch:
    """CoreRuntime 对一次 channel/loop 输入的调度结果。"""
    reply_text: str
    run_id: str | None = None
    plan: "TaskPlan | None" = None
    agent_request: "AgentRunRequest | None" = None
    channel_target: ChannelTarget | None = None
    handled_locally: bool = False


@dataclass(frozen=True)
class TaskPlan:
    """路由器为 Agent run 选择出的意图、skills 和用户提示。"""
    intent: str
    skill_names: tuple[str, ...]
    ack: str
    requires_agent: bool = True


@dataclass(frozen=True)
class AgentSettings:
    """Agent provider、模式、模型和 reasoning 的可覆盖配置。"""
    provider: str | None = None
    mode: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class AgentRunRequest:
    """CoreRuntime 交给 AgentWrapper 的规范化运行请求。"""
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
    """具体 Agent provider 执行结束后的统一结果。"""
    run_id: str
    status: str
    response_text: str
    session_id: str | None
    result_path: Path
    error: str | None = None


@dataclass(frozen=True)
class AgentEvent:
    """provider 输出给 channel sink 的结构化事件。"""
    run_id: str
    kind: str
    message: str
    phase: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class AgentEventSink(Protocol):
    """接收 AgentEvent 的 channel-neutral 协议。"""
    def emit(self, event: AgentEvent) -> None:
        """Receive a structured, channel-neutral agent event."""


def merge_agent_settings(
    defaults: AgentSettings,
    overrides: AgentSettings,
) -> AgentSettings:
    """按会话覆盖优先、runtime 默认兜底的顺序合并 Agent 设置。"""
    return AgentSettings(
        provider=overrides.provider or defaults.provider or "codex",
        mode=overrides.mode or defaults.mode or "standard",
        model=overrides.model or defaults.model,
        reasoning_effort=overrides.reasoning_effort or defaults.reasoning_effort,
    )
