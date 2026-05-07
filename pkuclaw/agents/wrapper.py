"""AgentWrapper compiles CoreRuntime requests into provider runs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pkuclaw.agents.base import Agent, AgentRunContext, AgentRunPaths
from pkuclaw.config import Settings
from pkuclaw.core import logging as log
from pkuclaw.core.models import (
    DEFAULT_AGENT_MODE,
    DEFAULT_AGENT_MODEL,
    DEFAULT_AGENT_PROVIDER,
    DEFAULT_AGENT_REASONING_EFFORT,
    AgentEventSink,
    AgentResult,
    AgentRunRequest,
    AgentSettings,
    TaskPlan,
    merge_agent_settings,
)
from pkuclaw.core.store import RunRecord, Store
from pkuclaw.runtime.config import (
    RuntimeConfigStore,
    describe_notify_policy,
)
from pkuclaw.runtime.prompts import read_prompt_templates, render_prompt_template
from pkuclaw.agents.providers.codex import CodexAgent
from pkuclaw.runtime.skills import (
    OUTBOX_SKILL_NAME,
    load_skill_registry,
    render_skill_catalog,
    render_suggested_skills,
)


@dataclass(frozen=True)
class PreparedAgentRun:
    """Summary returned by prepare before channel/loop execution."""

    run_id: str
    request: AgentRunRequest
    plan: TaskPlan


class AgentWrapper:
    """Run compiler that turns CoreRuntime requests into provider executions."""

    def __init__(
        self,
        *,
        settings: Settings,
        store: Store,
        runtime_config: RuntimeConfigStore,
        repo_root: Path | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.runtime_config = runtime_config
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self._codex = CodexAgent(settings=settings, repo_root=self.repo_root)

    def prepare(self, request: AgentRunRequest, plan: TaskPlan) -> PreparedAgentRun:
        """Create a queued run record and return a runnable handle."""

        run = self.store.create_run(
            conversation_id=request.conversation_id,
            user_text=request.text,
            source=request.source,
            metadata=_request_metadata(request),
        )
        log.event(
            "AgentWrapper prepared run: "
            f"source={request.source}, run={run.run_id}, "
            f"suggested_skills={','.join(request.suggested_skills) or 'none'}"
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
        """Build context/prompt, invoke the concrete Agent, and persist results."""

        run = self.store.get_run(run_id)
        context = self._build_context(run=run, request=request, plan=plan)
        self.store.update_run_metadata(
            run_id,
            _execution_metadata(context),
        )

        try:
            prompt = self.build_run_prompt(context)
            context.paths.run_dir.mkdir(parents=True, exist_ok=True)
            context.paths.prompt_path.write_text(prompt, encoding="utf-8")
            self.store.mark_run_running(run_id)
            log.ok(
                "AgentWrapper prompt ready: "
                f"run={run_id}, provider={context.agent_settings.provider}, "
                f"chars={len(prompt)}, prompt={context.paths.prompt_path}"
            )
            agent = self._select_agent(context.agent_settings)
            result = agent.execute(context, prompt, sink)
        except Exception as exc:
            error = str(exc)
            self.store.mark_run_failed(
                run_id,
                error,
                response_text=error,
                result_path=context.paths.result_path,
            )
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
            error = result.error or result.response_text
            self.store.mark_run_failed(
                run_id,
                error,
                response_text=result.response_text,
                result_path=result.result_path,
            )
        return result

    def _build_context(
        self,
        *,
        run: RunRecord,
        request: AgentRunRequest,
        plan: TaskPlan,
    ) -> AgentRunContext:
        """Hot-load runtime files and collect prompt materials."""

        conversation = self.store.ensure_conversation(run.conversation_id)
        runtime = self.runtime_config.read_snapshot()
        agent_settings = merge_agent_settings(
            runtime.agent,
            conversation.agent_settings,
        )
        provider = agent_settings.provider or "codex"
        paths = _run_paths(
            self.settings.app.data_dir / "agent_runs" / provider,
            run.run_id,
        )
        skills_dir = self.runtime_config.config_dir / "skills"
        skill_registry = load_skill_registry(
            self.runtime_config.config_dir / "skills.json",
            skills_dir=skills_dir,
        )
        if skill_registry.warnings:
            for warning in skill_registry.warnings:
                log.warn(warning)
        skill_catalog_text = render_skill_catalog(
            registry=skill_registry,
            skills_dir=skills_dir,
            source=request.source,
        )
        suggested_skills_text = render_suggested_skills(
            request.suggested_skills,
            skills_dir=skills_dir,
            registry=skill_registry,
            source=request.source,
        )
        warnings = (*runtime.warnings, *skill_registry.warnings)
        return AgentRunContext(
            run=run,
            request=request,
            plan=plan,
            conversation=conversation,
            runtime=runtime,
            agent_settings=agent_settings,
            paths=paths,
            repo_root=self.repo_root,
            recent_runs_text="",
            skill_catalog_text=skill_catalog_text,
            rendered_skills=suggested_skills_text,
            prompt_fragments="",
            outbox_script_text=_outbox_script_text(),
            warnings=warnings,
        )

    def build_run_prompt(self, context: AgentRunContext) -> str:
        """Dispatch prompt construction by the two supported run sources."""

        if context.request.source == "realtime":
            return self._build_realtime_prompt(context)
        if context.request.source == "loop":
            return self._build_loop_prompt(context)
        raise RuntimeError(f"unsupported agent run source: {context.request.source}")

    def _build_realtime_prompt(self, context: AgentRunContext) -> str:
        """Build the realtime task prompt from runtime templates."""

        templates = read_prompt_templates(self.runtime_config.config_dir)
        suggested = (
            render_prompt_template(
                templates.realtime.suggested_skills_template,
                {"suggested_skills": context.rendered_skills},
            )
            if context.rendered_skills.strip() != "- none"
            else ""
        )
        return render_prompt_template(
            templates.realtime.template,
            {
                "skill_catalog": context.skill_catalog_text,
                "suggested_skills_section": suggested,
                "user_request": context.request.text,
            },
        )

    def _build_loop_prompt(self, context: AgentRunContext) -> str:
        """Build the scheduled loop prompt from runtime templates."""

        templates = read_prompt_templates(self.runtime_config.config_dir)
        channel_context = context.request.channel_context
        notify_policy = context.runtime.notifications.policy
        return render_prompt_template(
            templates.loop.template,
            {
                "loop_id": channel_context.get("loop_id") or "unknown",
                "scheduled_at": channel_context.get("scheduled_at") or "unknown",
                "sink_mode": context.request.sink_mode,
                "notify_policy": notify_policy,
                "notify_policy_description": describe_notify_policy(notify_policy),
                "notification_target": _notification_target_text(channel_context.get("target")),
                "channel_outbox_skill": context.outbox_script_text,
                "skill_catalog": context.skill_catalog_text,
                "suggested_skills": context.rendered_skills,
                "task": context.request.text,
            },
        )

    def _effective_model_text(self, context: AgentRunContext) -> str:
        """Return the effective model name."""

        return (
            context.agent_settings.model
            or self.settings.codex.model
            or DEFAULT_AGENT_MODEL
        )

    def _effective_reasoning_text(self, context: AgentRunContext) -> str:
        """Return the effective reasoning effort."""

        return context.agent_settings.reasoning_effort or DEFAULT_AGENT_REASONING_EFFORT

    def _select_agent(self, agent_settings: AgentSettings) -> Agent:
        """Select a concrete Agent provider."""

        provider = agent_settings.provider or "codex"
        if provider == "codex":
            return self._codex
        raise RuntimeError(f"unsupported agent provider: {provider}")


def _run_paths(base_dir: Path, run_id: str) -> AgentRunPaths:
    """Build standard artifact paths for one provider run."""

    run_dir = base_dir / run_id
    return AgentRunPaths(
        run_dir=run_dir,
        prompt_path=run_dir / "prompt.md",
        result_path=run_dir / "result.md",
        stdout_path=run_dir / "stdout.jsonl",
        stderr_path=run_dir / "stderr.log",
    )


def _notification_target_text(value: object) -> str:
    """Render the loop notification target compactly."""

    if isinstance(value, dict):
        channel = value.get("channel") or "unknown"
        target_type = value.get("target_type") or "unknown"
        target_id = value.get("target_id") or "unknown"
        return f"`{channel}` / `{target_type}` / `{target_id}`"
    return "not configured"


def _outbox_script_text() -> str:
    """Render concise outbox script instructions."""

    return (
        "Use the channel outbox skill only when you need to send text/image/file "
        "outside the normal realtime streaming card. "
        f"Read `configs/runtime/skills/{OUTBOX_SKILL_NAME}` and call the documented "
        "queue-based Python script."
    )


def _request_metadata(request: AgentRunRequest) -> dict[str, object]:
    """Build the queued-run structured metadata from the normalized request."""

    channel_context = dict(request.channel_context)
    return {
        "source": request.source,
        "channel": {
            "name": request.channel,
            "sender_id": request.sender_id,
            "target": channel_context.get("target"),
            "event_id": channel_context.get("event_id"),
        },
        "loop": _loop_metadata(request, channel_context),
        "sink_mode": request.sink_mode,
        "suggested_skills": list(request.suggested_skills),
    }


def _loop_metadata(
    request: AgentRunRequest,
    channel_context: dict[str, object],
) -> dict[str, object] | None:
    """Return loop-specific metadata, or None for realtime runs."""

    if request.source != "loop":
        return None
    return {
        "id": channel_context.get("loop_id"),
        "notify_policy": channel_context.get("notify_policy"),
        "sink_mode": request.sink_mode,
        "scheduled_at": channel_context.get("scheduled_at"),
        "suggested_skills": list(request.suggested_skills),
    }


def _execution_metadata(context: AgentRunContext) -> dict[str, object]:
    """Build the structured facts known when the run is ready to execute."""

    return {
        "agent": {
            "provider": context.agent_settings.provider or DEFAULT_AGENT_PROVIDER,
            "mode": context.agent_settings.mode or DEFAULT_AGENT_MODE,
            "model": context.agent_settings.model or DEFAULT_AGENT_MODEL,
            "reasoning_effort": (
                context.agent_settings.reasoning_effort
                or DEFAULT_AGENT_REASONING_EFFORT
            ),
        },
        "paths": {
            "run_dir": str(context.paths.run_dir),
            "prompt": str(context.paths.prompt_path),
            "stdout": str(context.paths.stdout_path),
            "stderr": str(context.paths.stderr_path),
            "result": str(context.paths.result_path),
        },
        "runtime": {
            "config": str(context.runtime.path),
            "warnings": list(context.warnings),
        },
    }
