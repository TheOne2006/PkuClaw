from __future__ import annotations

from typing import Protocol

from pkuclaw.core.models import CodeAgentEventSink, CodeAgentResult, TaskPlan
from pkuclaw.core.store import RunRecord


class CodeAgent(Protocol):
    """Common contract for Codex, Claude Code, Kimi Code, etc."""

    name: str

    def run(
        self,
        run: RunRecord,
        plan: TaskPlan,
        sink: CodeAgentEventSink,
    ) -> CodeAgentResult:
        """Execute one backend task and persist artifacts/state."""
