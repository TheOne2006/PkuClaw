from __future__ import annotations

from pkuclaw.agents.wrapper import AgentWrapper
from pkuclaw.core import logging as log
from pkuclaw.core.control import mode_label, parse_control_command
from pkuclaw.core.models import (
    AgentEventSink,
    AgentResult,
    AgentRunRequest,
    ChannelMessage,
    CoreDispatch,
    TaskPlan,
    merge_agent_settings,
)
from pkuclaw.core.router import classify_message
from pkuclaw.core.store import Store
from pkuclaw.runtime_config import RuntimeConfigLoader, RuntimeLoopConfig


class CoreRuntime:
    """Daemon control plane for channel ingress, scheduled runs, and agent execution."""

    def __init__(
        self,
        *,
        store: Store,
        agent_wrapper: AgentWrapper,
        runtime_config: RuntimeConfigLoader,
    ) -> None:
        self.store = store
        self.agent_wrapper = agent_wrapper
        self.runtime_config = runtime_config

    def ingest(self, message: ChannelMessage) -> CoreDispatch:
        command = parse_control_command(text=message.text, event_key=message.event_key)
        if command is not None:
            reply = self._handle_control(
                conversation_id=message.conversation_id,
                kind=command.kind,
                value=command.value,
            )
            return CoreDispatch(reply_text=reply, handled_locally=True)
        if message.event_key:
            return CoreDispatch(
                reply_text=f"未知控制动作：{message.event_key}",
                handled_locally=True,
            )

        plan = classify_message(message.text)
        agent_request = AgentRunRequest(
            source="realtime",
            conversation_id=message.conversation_id,
            text=message.text,
            intent=plan.intent,
            skill_names=plan.skill_names,
            channel=message.channel,
            sender_id=message.sender_id,
            channel_context={},
            sink_mode="streaming",
        )
        prepared = self.agent_wrapper.prepare(agent_request, plan)
        log.event(
            "realtime dispatch: "
            f"conversation={_short_id(message.conversation_id)}, "
            f"run={prepared.run_id}, intent={plan.intent}, "
            f"skills={','.join(plan.skill_names) or 'base'}"
        )
        return CoreDispatch(
            reply_text=f"{plan.ack}\n\nrun_id: `{prepared.run_id}`",
            run_id=prepared.run_id,
            plan=plan,
            agent_request=agent_request,
        )

    def create_loop_run(self, *, loop_id: str | None = None) -> CoreDispatch:
        runtime = self.runtime_config.read()
        loop = _select_loop(runtime.loops, loop_id=loop_id)
        text = loop.prompt or (
            "检查课程状态、教学网通知和本地数据。如果没有重要变化，保持静默。"
        )
        skill_names = loop.skill_names or ("tasks/sync-notices.md",)
        plan = TaskPlan(
            intent="loop",
            skill_names=skill_names,
            ack=f"Loop run queued: {loop.id}.",
        )
        request = AgentRunRequest(
            source="loop",
            conversation_id=f"daemon:loop:{loop.id}",
            text=text,
            intent=plan.intent,
            skill_names=plan.skill_names,
            channel=None,
            sender_id=None,
            channel_context={
                "loop_id": loop.id,
                "notify_policy": loop.notify_policy,
            },
            sink_mode=loop.sink_mode,
        )
        prepared = self.agent_wrapper.prepare(request, plan)
        return CoreDispatch(
            reply_text=f"Loop run queued: {loop.id}.",
            run_id=prepared.run_id,
            plan=plan,
            agent_request=request,
        )

    def run_agent(
        self,
        run_id: str,
        plan: TaskPlan,
        request: AgentRunRequest,
        sink: AgentEventSink,
    ) -> AgentResult:
        return self.agent_wrapper.run(
            run_id=run_id,
            request=request,
            plan=plan,
            sink=sink,
        )

    def _handle_control(
        self,
        *,
        conversation_id: str,
        kind: str,
        value: str | None,
    ) -> str:
        if kind == "set_provider":
            if value is None:
                raise RuntimeError("provider value is required")
            conversation = self.store.update_agent_settings(
                conversation_id,
                provider=value,
            )
            return f"已切换 Agent provider 到 {conversation.agent_settings.provider}。"

        if kind == "set_mode":
            if value is None:
                raise RuntimeError("mode value is required")
            conversation = self.store.update_agent_settings(
                conversation_id,
                mode=value,
            )
            log.ok(
                "agent mode switched: "
                f"conversation={_short_id(conversation_id)}, "
                f"mode={conversation.agent_settings.mode}"
            )
            return (
                "已切换 Agent 到 "
                f"{mode_label(conversation.agent_settings.mode)} 模式。"
            )

        if kind == "set_model":
            if value is None:
                raise RuntimeError("model value is required")
            conversation = self.store.update_agent_settings(
                conversation_id,
                model=value,
            )
            return f"已切换 Agent 模型到 {conversation.agent_settings.model}。"

        if kind == "set_reasoning":
            if value is None:
                raise RuntimeError("reasoning value is required")
            conversation = self.store.update_agent_settings(
                conversation_id,
                reasoning_effort=value,
            )
            return (
                "已切换 Agent 思考强度到 "
                f"{conversation.agent_settings.reasoning_effort}。"
            )

        if kind == "status":
            conversation = self.store.ensure_conversation(conversation_id)
            runtime = self.runtime_config.read()
            agent_settings = merge_agent_settings(
                runtime.agent,
                conversation.agent_settings,
            )
            counts = self.store.counts_by_status()
            status_text = ", ".join(
                f"{name}={count}" for name, count in sorted(counts.items())
            )
            return (
                f"Agent：{agent_settings.provider}\n"
                f"Agent mode：{mode_label(agent_settings.mode or 'standard')}\n"
                f"Model：{agent_settings.model or '默认'}\n"
                f"Reasoning：{agent_settings.reasoning_effort or '默认'}\n"
                f"Runtime config：{runtime.path}\n"
                f"Runtime warnings：{'; '.join(runtime.warnings) or '无'}\n"
                f"Agent thread：{conversation.agent_session_id or '无'}\n"
                f"任务统计：{status_text or '暂无任务'}"
            )

        if kind == "recent_runs":
            recent = self.store.recent_runs(conversation_id=conversation_id, limit=5)
            if not recent:
                return "最近没有任务。"
            lines = [
                (
                    f"- {run.run_id[:8]} [{run.intent}/{run.status}] "
                    f"{' '.join(run.user_text.split())[:40]}"
                )
                for run in recent
            ]
            return "最近任务：\n" + "\n".join(lines)

        raise RuntimeError(f"unknown control command: {kind}")


def _short_id(value: str) -> str:
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-4:]}"


def _select_loop(
    loops: tuple[RuntimeLoopConfig, ...],
    *,
    loop_id: str | None,
) -> RuntimeLoopConfig:
    enabled = [loop for loop in loops if loop.enabled]
    if loop_id is not None:
        for loop in enabled:
            if loop.id == loop_id:
                return loop
        raise RuntimeError(f"runtime loop not found or disabled: {loop_id}")
    if enabled:
        return enabled[0]
    raise RuntimeError("no enabled runtime loops")
