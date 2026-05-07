"""定义 Agent provider 边界和一次运行所需的上下文数据。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pkuclaw.core.models import (
    AgentEventSink,
    AgentResult,
    AgentRunRequest,
    AgentSettings,
    TaskPlan,
)
from pkuclaw.core.store import Conversation, RunRecord
from pkuclaw.runtime.config import RuntimeConfig


@dataclass(frozen=True)
class AgentRunPaths:
    """一次 Agent run 产生和读取的文件路径集合。"""
    run_dir: Path
    prompt_path: Path
    result_path: Path
    stdout_path: Path
    stderr_path: Path


@dataclass(frozen=True)
class AgentRunContext:
    """Agent provider 执行时需要的完整只读上下文。"""
    run: RunRecord
    request: AgentRunRequest
    plan: TaskPlan
    conversation: Conversation
    runtime: RuntimeConfig
    agent_settings: AgentSettings
    paths: AgentRunPaths
    repo_root: Path
    recent_runs_text: str
    skill_catalog_text: str
    rendered_skills: str
    prompt_fragments: str
    outbox_script_text: str
    warnings: tuple[str, ...]


class Agent(Protocol):
    """所有具体 Agent provider 需要实现的执行协议。"""
    name: str

    def execute(
        self,
        context: AgentRunContext,
        prompt: str,
        sink: AgentEventSink,
    ) -> AgentResult:
        """Execute one prepared agent run."""
