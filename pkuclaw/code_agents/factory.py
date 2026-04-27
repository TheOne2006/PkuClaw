from __future__ import annotations

from pathlib import Path

from pkuclaw.code_agents.base import CodeAgent
from pkuclaw.code_agents.codex import CodexAgent
from pkuclaw.config import Settings
from pkuclaw.core.models import (
    CodeAgentEventSink,
    CodeAgentResult,
    TaskPlan,
    merge_agent_settings,
)
from pkuclaw.core.store import RunRecord, Store
from pkuclaw.runtime_config import RuntimeConfigLoader


class ConfiguredCodeAgent:
    def __init__(
        self,
        *,
        settings: Settings,
        store: Store,
        runtime_config: RuntimeConfigLoader,
        repo_root: Path | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.runtime_config = runtime_config
        self._codex = CodexAgent(
            settings=settings,
            store=store,
            runtime_config=runtime_config,
            repo_root=repo_root,
        )

    @property
    def name(self) -> str:
        return (
            self.runtime_config.read().code_agent.provider
            or self.settings.code_agent.provider
        )

    def run(
        self,
        run: RunRecord,
        plan: TaskPlan,
        sink: CodeAgentEventSink,
    ) -> CodeAgentResult:
        conversation = self.store.ensure_conversation(run.conversation_id)
        runtime = self.runtime_config.read()
        agent_settings = merge_agent_settings(
            runtime.code_agent,
            conversation.agent_settings,
        )
        if agent_settings.provider == "codex":
            return self._codex.run(run, plan, sink)
        raise RuntimeError(
            f"unsupported code agent provider: {agent_settings.provider}"
        )


def build_code_agent(
    *,
    settings: Settings,
    store: Store,
    runtime_config: RuntimeConfigLoader,
    repo_root: Path | None = None,
) -> CodeAgent:
    return ConfiguredCodeAgent(
        settings=settings,
        store=store,
        runtime_config=runtime_config,
        repo_root=repo_root,
    )
