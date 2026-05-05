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
from pkuclaw.runtime_config import RuntimeConfig


@dataclass(frozen=True)
class AgentRunPaths:
    run_dir: Path
    prompt_path: Path
    result_path: Path
    stdout_path: Path
    stderr_path: Path


@dataclass(frozen=True)
class AgentRunContext:
    run: RunRecord
    request: AgentRunRequest
    plan: TaskPlan
    conversation: Conversation
    runtime: RuntimeConfig
    agent_settings: AgentSettings
    paths: AgentRunPaths
    repo_root: Path
    recent_runs_text: str
    rendered_skills: str
    prompt_fragments: str
    mcp_tools_text: str
    warnings: tuple[str, ...]


class Agent(Protocol):
    name: str

    def execute(
        self,
        context: AgentRunContext,
        prompt: str,
        sink: AgentEventSink,
    ) -> AgentResult:
        """Execute one prepared agent run."""
