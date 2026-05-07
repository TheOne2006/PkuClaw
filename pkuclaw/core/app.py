"""CoreRuntime 控制面，统一 channel、loop、MCP 和 Agent 执行入口。"""
from __future__ import annotations

from concurrent.futures import Executor
from dataclasses import asdict
from types import MappingProxyType
from typing import Any, Mapping

from pkuclaw.agents.wrapper import AgentWrapper
from pkuclaw.channels.base import (
    ChannelInboundMessage,
    ChannelOutboundBackend,
    ChannelOutboundResult,
    ChannelTarget,
)
from pkuclaw.core import logging as log
from pkuclaw.core.control import mode_label, parse_control_command
from pkuclaw.core.models import (
    AgentEventSink,
    AgentResult,
    AgentRunRequest,
    CoreDispatch,
    TaskPlan,
    merge_agent_settings,
)
from pkuclaw.core.router import classify_message
from pkuclaw.core.store import Store, utc_now
from pkuclaw.runtime_config import (
    RuntimeConfig,
    RuntimeConfigStore,
    RuntimeConfigWriteResult,
    RuntimeLoopConfig,
)


class CoreRuntime:
    """Daemon control plane for channel ingress, scheduled runs, and agent execution."""

    def __init__(
        self,
        *,
        store: Store,
        agent_wrapper: AgentWrapper,
        runtime_config: RuntimeConfigStore,
        run_executor: Executor | None = None,
    ) -> None:
        self.store = store
        self.agent_wrapper = agent_wrapper
        self.runtime_config = runtime_config
        self.run_executor = run_executor
        self._channel_backends: dict[str, ChannelOutboundBackend] = {}
        self.loop_manager: Any | None = None

    @property
    def channel_backends(self) -> Mapping[str, ChannelOutboundBackend]:
        """执行 channel backends 逻辑。"""
        return MappingProxyType(self._channel_backends)

    def register_channel_backend(self, backend: ChannelOutboundBackend) -> None:
        """Register one channel outbox backend under CoreRuntime control."""
        channel = str(backend.channel).strip()
        if not channel:
            raise RuntimeError("channel backend must declare a channel name")
        self._channel_backends[channel] = backend

    def attach_loop_manager(self, loop_manager: Any) -> None:
        """Record the CoreRuntime-owned scheduler instance built by bootstrap."""

        self.loop_manager = loop_manager

    def channel_backend(self, channel: str) -> ChannelOutboundBackend:
        """按 channel 名称读取已注册的 outbox backend。"""
        try:
            return self._channel_backends[channel]
        except KeyError as exc:
            raise RuntimeError(f"channel backend not registered: {channel}") from exc

    def send_channel_text(
        self,
        *,
        channel: str,
        target_type: str,
        target_id: str,
        text: str,
    ) -> ChannelOutboundResult:
        """通过指定 channel backend 发送文本消息。"""
        target = ChannelTarget(
            channel=channel,
            target_type=target_type,
            target_id=target_id,
        )
        return self.channel_backend(channel).send_text(target=target, text=text)

    def send_channel_card(
        self,
        *,
        channel: str,
        target_type: str,
        target_id: str,
        card: dict[str, Any],
    ) -> ChannelOutboundResult:
        """通过指定 channel backend 发送结构化卡片。"""
        target = ChannelTarget(
            channel=channel,
            target_type=target_type,
            target_id=target_id,
        )
        return self.channel_backend(channel).send_card(target=target, card=card)

    def send_channel_image(
        self,
        *,
        channel: str,
        target_type: str,
        target_id: str,
        image_path: str,
    ) -> ChannelOutboundResult:
        """通过指定 channel backend 发送图片。"""
        target = ChannelTarget(
            channel=channel,
            target_type=target_type,
            target_id=target_id,
        )
        return self.channel_backend(channel).send_image(
            target=target,
            image_path=image_path,
        )

    def update_channel_card(
        self,
        *,
        channel: str,
        card_id: str,
        card: dict[str, Any],
        sequence: int,
    ) -> ChannelOutboundResult:
        """通过指定 channel backend 更新外部卡片。"""
        return self.channel_backend(channel).update_card(
            card_id=card_id,
            card=card,
            sequence=sequence,
        )

    def runtime_get_status(
        self,
        *,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Return daemon status for MCP runtime read tools."""

        runtime = self.runtime_config.read_snapshot()
        agent_settings = runtime.agent
        conversation_payload: dict[str, Any] | None = None
        if conversation_id:
            conversation = self.store.ensure_conversation(conversation_id)
            agent_settings = merge_agent_settings(
                runtime.agent,
                conversation.agent_settings,
            )
            conversation_payload = {
                "conversation_id": conversation.conversation_id,
                "agent_session_id": conversation.agent_session_id,
                "agent_settings": _agent_settings_dict(conversation.agent_settings),
                "created_at": conversation.created_at,
                "updated_at": conversation.updated_at,
            }
        return {
            "runtime_config_path": str(runtime.path),
            "runtime_warnings": list(runtime.warnings),
            "agent_settings": _agent_settings_dict(agent_settings),
            "registered_channels": sorted(self._channel_backends),
            "run_counts": self.store.counts_by_status(),
            "active_conversations": self.store.active_conversation_count(),
            "loops": [_loop_config_dict(loop) for loop in runtime.loops],
            "conversation": conversation_payload,
        }

    def runtime_get_config(self) -> dict[str, Any]:
        """Return the current hot-loaded runtime config snapshot."""

        return _runtime_config_dict(self.runtime_config.read_snapshot())

    def runtime_list_loops(self) -> list[dict[str, Any]]:
        """Return the current hot-loaded loop specs."""

        return [
            _loop_config_dict(loop)
            for loop in self.runtime_config.read_snapshot().loops
        ]

    def add_loop(
        self,
        *,
        loop: Mapping[str, Any],
        actor: str = "agent:mcp",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Add one runtime loop through validated backup/atomic/audit write path."""

        self._ensure_runtime_write_allowed(add_loop=True)
        return self._record_runtime_write_result(
            self.runtime_config.add_loop(loop),
            actor=actor,
            run_id=run_id,
        )

    def update_loop(
        self,
        *,
        loop_id: str,
        updates: Mapping[str, Any],
        actor: str = "agent:mcp",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Update one runtime loop through validated backup/atomic/audit write path."""

        self._ensure_runtime_write_allowed(add_loop=False)
        return self._record_runtime_write_result(
            self.runtime_config.update_loop(loop_id, updates),
            actor=actor,
            run_id=run_id,
        )

    def enable_loop(
        self,
        *,
        loop_id: str,
        actor: str = "agent:mcp",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Enable one runtime loop through validated backup/atomic/audit write path."""

        self._ensure_runtime_write_allowed(add_loop=False)
        return self._record_runtime_write_result(
            self.runtime_config.enable_loop(loop_id),
            actor=actor,
            run_id=run_id,
        )

    def disable_loop(
        self,
        *,
        loop_id: str,
        actor: str = "agent:mcp",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Disable one runtime loop through validated backup/atomic/audit write path."""

        self._ensure_runtime_write_allowed(add_loop=False)
        return self._record_runtime_write_result(
            self.runtime_config.disable_loop(loop_id),
            actor=actor,
            run_id=run_id,
        )

    def _ensure_runtime_write_allowed(self, *, add_loop: bool) -> None:
        """根据 runtime permissions 判断 Agent 是否允许写配置。"""
        permissions = self.runtime_config.read_snapshot().permissions
        if add_loop and not permissions.agent_can_add_loop:
            raise RuntimeError("runtime policy denies adding loops")
        if not add_loop and not permissions.agent_can_update_runtime:
            raise RuntimeError("runtime policy denies runtime updates")

    def _record_runtime_write_result(
        self,
        result: RuntimeConfigWriteResult,
        *,
        actor: str,
        run_id: str | None,
    ) -> dict[str, Any]:
        """把 RuntimeConfigStore 写入结果记录到 Store 审计表。"""
        audit_id = self.store.record_runtime_change(
            run_id=run_id,
            actor=actor,
            file=str(result.file),
            action=result.action,
            old_hash=result.old_hash,
            new_hash=result.new_hash,
            diff_summary=result.diff_summary,
            status=result.status,
        )
        return _runtime_write_result_dict(result, audit_id=audit_id)

    def runtime_list_recent_runs(
        self,
        *,
        conversation_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return recent runs from the runtime store."""

        return [
            _run_record_dict(run)
            for run in self.store.recent_runs(
                conversation_id=conversation_id,
                limit=max(1, min(limit, 50)),
            )
        ]

    def runtime_get_run(self, *, run_id: str) -> dict[str, Any]:
        """Return one run plus metadata from the runtime store."""

        return {
            **_run_record_dict(self.store.get_run(run_id)),
            "metadata": self.store.get_run_metadata(run_id),
        }

    def ingest_channel_message(self, message: ChannelInboundMessage) -> CoreDispatch:
        """Ingest one normalized channel message through the runtime control plane."""
        command = parse_control_command(text=message.text, event_key=message.event_key)
        if command is not None:
            # Control commands are daemon-local mutations/reads, so they bypass
            # AgentWrapper and return a direct channel reply.
            reply = self._handle_control(
                conversation_id=message.conversation_id,
                kind=command.kind,
                value=command.value,
            )
            return CoreDispatch(
                reply_text=reply,
                channel_target=message.target,
                handled_locally=True,
            )
        if message.event_key:
            return CoreDispatch(
                reply_text=f"未知控制动作：{message.event_key}",
                channel_target=message.target,
                handled_locally=True,
            )

        plan = classify_message(message.text)
        return self.create_realtime_run(message=message, plan=plan)

    def create_realtime_run(
        self,
        *,
        message: ChannelInboundMessage,
        plan: TaskPlan | None = None,
    ) -> CoreDispatch:
        """Create a realtime agent run from a normalized channel message."""
        plan = plan or classify_message(message.text)
        agent_request = AgentRunRequest(
            source="realtime",
            conversation_id=message.conversation_id,
            text=message.text,
            intent=plan.intent,
            skill_names=plan.skill_names,
            channel=message.channel,
            sender_id=message.sender_id,
            channel_context=message.channel_context(),
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
            channel_target=message.target,
        )

    def create_loop_run(
        self,
        *,
        loop_id: str | None = None,
        scheduled_at: str | None = None,
    ) -> CoreDispatch:
        """从当前 runtime loop spec 创建一条 silent-by-default 的 loop run。"""
        runtime = self.runtime_config.read_snapshot()
        loop = _select_loop(runtime.loops, loop_id=loop_id)
        text = loop.prompt or "Run this configured periodic loop. Stay silent unless important."
        skill_names = loop.skill_names
        scheduled_at = scheduled_at or utc_now()
        target = _loop_default_target(loop)
        # Loop runs are silent by default; default channel target is only a
        # notification hint for Agent MCP tools when something important happens.
        channel_context: dict[str, Any] = {
            "loop_id": loop.id,
            "notify_policy": loop.notify_policy,
            "sink_mode": loop.sink_mode,
            "scheduled_at": scheduled_at,
        }
        if target is not None:
            channel_context["channel"] = target["channel"]
            channel_context["target"] = target
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
            channel=loop.default_channel,
            sender_id=None,
            channel_context=channel_context,
            sink_mode=loop.sink_mode,
        )
        prepared = self.agent_wrapper.prepare(request, plan)
        metadata: dict[str, Any] = {
            "source": "loop",
            "loop_id": loop.id,
            "notify_policy": loop.notify_policy,
            "sink_mode": loop.sink_mode,
            "scheduled_at": scheduled_at,
        }
        if target is not None:
            metadata["channel"] = target["channel"]
            metadata["target"] = target
        self.store.update_run_metadata(prepared.run_id, metadata)
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
        """把已准备好的 run 委托给 AgentWrapper 执行。"""
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
        """执行本地控制命令，不启动 Agent。"""
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
            runtime = self.runtime_config.read_snapshot()
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
    """内部辅助函数，封装 short id 逻辑。"""
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-4:]}"


def _runtime_config_dict(runtime: RuntimeConfig) -> dict[str, Any]:
    """把 RuntimeConfig 转换为 MCP/状态接口可序列化字典。"""
    return {
        "path": str(runtime.path),
        "schema_version": runtime.schema_version,
        "warnings": list(runtime.warnings),
        "agent": _agent_settings_dict(runtime.agent),
        "codex": asdict(runtime.codex),
        "loops": [_loop_config_dict(loop) for loop in runtime.loops],
        "prompt": {
            "fragment_paths": list(runtime.prompt.fragment_paths),
            "default_skill_names": list(runtime.prompt.default_skill_names),
        },
        "notifications": asdict(runtime.notifications),
        "permissions": asdict(runtime.permissions),
    }


def _runtime_write_result_dict(
    result: RuntimeConfigWriteResult,
    *,
    audit_id: int,
) -> dict[str, Any]:
    """把配置写入结果和审计 ID 转换为 API 响应字典。"""
    return {
        "action": result.action,
        "status": result.status,
        "file": str(result.file),
        "backup_path": str(result.backup_path) if result.backup_path else None,
        "audit": {
            "id": audit_id,
            "status": "recorded",
        },
        "old_hash": result.old_hash,
        "new_hash": result.new_hash,
        "diff_summary": result.diff_summary,
        "runtime_config": _runtime_config_dict(result.config),
        "loops": [_loop_config_dict(loop) for loop in result.config.loops],
    }


def _agent_settings_dict(settings: Any) -> dict[str, Any]:
    """把 AgentSettings 或兼容对象转换为字典。"""
    return {
        "provider": settings.provider,
        "mode": settings.mode,
        "model": settings.model,
        "reasoning_effort": settings.reasoning_effort,
    }


def _loop_config_dict(loop: RuntimeLoopConfig) -> dict[str, Any]:
    """把 RuntimeLoopConfig 转换为字典。"""
    return {
        "id": loop.id,
        "enabled": loop.enabled,
        "interval_seconds": loop.interval_seconds,
        "prompt": loop.prompt,
        "skill_names": list(loop.skill_names),
        "sink_mode": loop.sink_mode,
        "notify_policy": loop.notify_policy,
        "default_channel": loop.default_channel,
        "default_target_type": loop.default_target_type,
        "default_target_id": loop.default_target_id,
        "prevent_overlap": loop.prevent_overlap,
        "max_concurrent_runs": loop.max_concurrent_runs,
    }


def _run_record_dict(run: Any) -> dict[str, Any]:
    """把 RunRecord 转换为 MCP/状态接口字典。"""
    return {
        "run_id": run.run_id,
        "conversation_id": run.conversation_id,
        "status": run.status,
        "intent": run.intent,
        "user_text": run.user_text,
        "response_text": run.response_text,
        "result_path": run.result_path,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "finished_at": run.finished_at,
    }


def _select_loop(
    loops: tuple[RuntimeLoopConfig, ...],
    *,
    loop_id: str | None,
) -> RuntimeLoopConfig:
    """从 enabled loops 中选择指定 loop 或第一个可用 loop。"""
    enabled = [loop for loop in loops if loop.enabled]
    if loop_id is not None:
        for loop in enabled:
            if loop.id == loop_id:
                return loop
        raise RuntimeError(f"runtime loop not found or disabled: {loop_id}")
    if enabled:
        return enabled[0]
    raise RuntimeError("no enabled runtime loops")


def _loop_default_target(loop: RuntimeLoopConfig) -> dict[str, str] | None:
    """把 loop 默认通知目标转换为 channel target 字典。"""
    if not (
        loop.default_channel
        and loop.default_target_type
        and loop.default_target_id
    ):
        return None
    return {
        "channel": loop.default_channel,
        "target_type": loop.default_target_type,
        "target_id": loop.default_target_id,
    }
