from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pkuclaw.agents.base import Agent, AgentRunContext, AgentRunPaths
from pkuclaw.config import Settings
from pkuclaw.core import logging as log
from pkuclaw.core.models import (
    AgentEventSink,
    AgentResult,
    AgentRunRequest,
    AgentSettings,
    TaskPlan,
    merge_agent_settings,
)
from pkuclaw.core.store import RunRecord, Store
from pkuclaw.runtime_config import RuntimeConfig, RuntimeConfigLoader
from pkuclaw.code_agents.codex import CodexAgent
from pkuclaw.code_agents.subskills import render_subskills


@dataclass(frozen=True)
class PreparedAgentRun:
    run_id: str
    request: AgentRunRequest
    plan: TaskPlan


class AgentWrapper:
    """Daemon-owned layer that turns PkuClaw context into agent work."""

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
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self._codex = CodexAgent(settings=settings, repo_root=self.repo_root)

    def prepare(self, request: AgentRunRequest, plan: TaskPlan) -> PreparedAgentRun:
        run = self.store.create_run(
            conversation_id=request.conversation_id,
            user_text=request.text,
            intent=request.intent,
            metadata={
                "source": request.source,
                "channel": request.channel,
                "sender_id": request.sender_id,
                "skill_names": list(request.skill_names),
                "channel_context": request.channel_context,
                "sink_mode": request.sink_mode,
            },
        )
        log.event(
            "AgentWrapper prepared run: "
            f"source={request.source}, run={run.run_id}, "
            f"intent={request.intent}, skills={','.join(request.skill_names) or 'base'}"
        )
        return PreparedAgentRun(run_id=run.run_id, request=request, plan=plan)

    def run(
        self,
        *,
        run_id: str,
        request: AgentRunRequest,
        plan: TaskPlan,
        sink: AgentEventSink,
    ) -> AgentResult:
        run = self.store.get_run(run_id)
        context = self._build_context(run=run, request=request, plan=plan)
        prompt = self.build_run_prompt(context)
        context.paths.run_dir.mkdir(parents=True, exist_ok=True)
        context.paths.prompt_path.write_text(prompt, encoding="utf-8")
        self.store.mark_run_running(
            run_id,
            prompt_path=context.paths.prompt_path,
            stdout_path=context.paths.stdout_path,
            stderr_path=context.paths.stderr_path,
        )
        self.store.update_run_metadata(
            run_id,
            {
                "runtime_config": str(context.runtime.path),
                "runtime_warnings": list(context.warnings),
                "provider": context.agent_settings.provider,
                "mode": context.agent_settings.mode,
                "model": context.agent_settings.model,
                "reasoning_effort": context.agent_settings.reasoning_effort,
                "run_dir": str(context.paths.run_dir),
            },
        )
        log.ok(
            "AgentWrapper prompt ready: "
            f"run={run_id}, provider={context.agent_settings.provider}, "
            f"chars={len(prompt)}, prompt={context.paths.prompt_path}"
        )

        try:
            agent = self._select_agent(context.agent_settings)
            result = agent.execute(context, prompt, sink)
        except Exception as exc:
            error = str(exc)
            self.store.mark_run_failed(run_id, error)
            log.fail(f"AgentWrapper run failed: run={run_id}, error={error}")
            raise

        if result.status == "succeeded":
            self.store.mark_run_succeeded(
                run_id,
                response_text=result.response_text,
                result_path=result.result_path,
                session_id=result.session_id,
            )
        else:
            self.store.mark_run_failed(run_id, result.error or result.response_text)
        return result

    def _build_context(
        self,
        *,
        run: RunRecord,
        request: AgentRunRequest,
        plan: TaskPlan,
    ) -> AgentRunContext:
        conversation = self.store.ensure_conversation(run.conversation_id)
        runtime = self.runtime_config.read()
        agent_settings = merge_agent_settings(
            _settings_from_runtime(runtime),
            conversation.agent_settings,
        )
        provider = agent_settings.provider or "codex"
        paths = _run_paths(
            self.settings.app.data_dir / "agent_runs" / provider,
            run.run_id,
        )
        skill_names = _merge_skill_names(
            runtime.prompt.default_skill_names,
            request.skill_names,
        )
        rendered_skills = render_subskills(
            skill_names,
            skills_dir=self.repo_root / "sub-skills",
        )
        return AgentRunContext(
            run=run,
            request=request,
            plan=plan,
            conversation=conversation,
            runtime=runtime,
            agent_settings=agent_settings,
            paths=paths,
            repo_root=self.repo_root,
            recent_runs_text=self._recent_runs_text(run),
            rendered_skills=rendered_skills,
            prompt_fragments=self._render_prompt_fragments(runtime),
            channel_tools_text=_channel_tools_text(),
            warnings=runtime.warnings,
        )

    def build_run_prompt(self, context: AgentRunContext) -> str:
        source_note = (
            "This is a realtime user-facing chat run."
            if context.request.source == "realtime"
            else "This is a periodic loop run. Stay silent unless important notification is needed."
        )
        warnings = "\n".join(f"- {item}" for item in context.warnings) or "- none"
        return f"""# PkuClaw Agent Run

You are an agent invoked by PkuClaw Daemon through AgentWrapper.
{source_note}

## Run Context

- Source: `{context.request.source}`
- Run ID: `{context.run.run_id}`
- Conversation/thread key: `{context.run.conversation_id}`
- Intent: `{context.plan.intent}`
- Repository root: `{context.repo_root}`
- Run directory: `{context.paths.run_dir}`
- Runtime config: `{context.runtime.path}`
- Runtime warnings:
{warnings}

## Agent Settings

- Provider: `{context.agent_settings.provider}`
- Mode: `{context.agent_settings.mode}`
- Model: `{self._effective_model_text(context)}`
- Reasoning effort: `{self._effective_reasoning_text(context)}`

## Operating Boundary

- CoreRuntime owns channel ingress/outbox, loop-triggered runs, state store access, runtime policy, and process-facing control.
- AgentWrapper owns prompt construction, runtime snapshot injection, selected skills, artifacts, and event normalization.
- You are the concrete Agent. Decide steps, inspect files, call tools, use pku3b from skill docs, and produce the final answer or state update.
- Do not treat pku3b as an MCP tool. Use pku3b according to the injected skill docs when needed.
- Homework submission requires explicit user confirmation.

## User-Facing Reply Style

- For realtime runs, write the final answer as a natural chat reply to the user.
- Do not mention prompt files, stdout files, run IDs, card layout, or internal artifacts unless the user asks about implementation/debugging.
- For loop runs, update local state and stay silent unless an important notification is needed.

## Daemon MCP Tools

{context.channel_tools_text}

## Prompt Fragments

{context.prompt_fragments or "- none"}

## Recent Runs

{context.recent_runs_text}

## PkuClaw Skills

{context.rendered_skills}

## Request

{context.request.text}
"""

    def _effective_model_text(self, context: AgentRunContext) -> str:
        return context.agent_settings.model or self.settings.codex.model or "default"

    def _effective_reasoning_text(self, context: AgentRunContext) -> str:
        if context.agent_settings.reasoning_effort:
            return context.agent_settings.reasoning_effort
        return {
            "fast": "low",
            "standard": "medium",
            "deep": "high",
        }.get(context.agent_settings.mode or "", "default")

    def _recent_runs_text(self, run: RunRecord) -> str:
        recent = self.store.recent_runs(conversation_id=run.conversation_id, limit=5)
        lines = [
            f"- {item.created_at} [{item.intent}/{item.status}] {item.user_text[:80]}"
            for item in recent
            if item.run_id != run.run_id
        ]
        return "\n".join(lines) or "- none"

    def _render_prompt_fragments(self, runtime: RuntimeConfig) -> str:
        blocks: list[str] = []
        for raw_path in runtime.prompt.fragment_paths:
            path = (self.repo_root / raw_path).resolve()
            try:
                if self.repo_root not in path.parents:
                    raise ValueError("fragment path escapes repository root")
                blocks.append(f"## {raw_path}\n\n{path.read_text(encoding='utf-8').strip()}")
            except Exception as exc:
                blocks.append(f"## {raw_path}\n\n[failed to load prompt fragment: {exc}]")
        return "\n\n---\n\n".join(blocks)

    def _select_agent(self, agent_settings: AgentSettings) -> Agent:
        provider = agent_settings.provider or "codex"
        if provider == "codex":
            return self._codex
        raise RuntimeError(f"unsupported agent provider: {provider}")


def _settings_from_runtime(runtime: RuntimeConfig) -> AgentSettings:
    return runtime.agent


def _run_paths(base_dir: Path, run_id: str) -> AgentRunPaths:
    run_dir = base_dir / run_id
    return AgentRunPaths(
        run_dir=run_dir,
        prompt_path=run_dir / "prompt.md",
        result_path=run_dir / "result.md",
        stdout_path=run_dir / "stdout.jsonl",
        stderr_path=run_dir / "stderr.log",
    )


def _merge_skill_names(
    default_names: tuple[str, ...],
    request_names: tuple[str, ...],
) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for name in (*default_names, *request_names):
        if name not in seen:
            merged.append(name)
            seen.add(name)
    return tuple(merged)


def _channel_tools_text() -> str:
    return """Daemon MCP tools may be available when the CoreRuntime MCP server is configured. Current V1 exposes channel outbox tools:

- `channel_send_text`: send a plain text notification through the current channel backend.
- `channel_send_card`: send a structured card through the current channel backend.
- `channel_send_image`: send an image through the current channel backend.
- `channel_update_card`: update a previously sent card.

Use channel tools only for proactive notifications or loop-triggered messages. Normal realtime replies are streamed by the active channel adapter and do not require calling channel tools. Runtime control tools are planned for config, loop, and status operations."""
