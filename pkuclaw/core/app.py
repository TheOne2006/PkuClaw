"""CoreRuntime for channel ingress, scheduled loop runs and Agent execution."""
from __future__ import annotations

from concurrent.futures import Executor
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
from pkuclaw.core.control import parse_control_command
from pkuclaw.core.models import (
    AgentEventSink,
    AgentResult,
    AgentRunRequest,
    CoreDispatch,
    TaskPlan,
)
from pkuclaw.core.store import Store, utc_now
from pkuclaw.runtime_config import RuntimeConfigStore, RuntimeLoopConfig


class CoreRuntime:
    """Control plane for channel ingress, loop-triggered runs and notifications."""

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
        """Return registered channel outbox backends."""

        return MappingProxyType(self._channel_backends)

    def register_channel_backend(self, backend: ChannelOutboundBackend) -> None:
        """Register one channel outbox backend under CoreRuntime control."""

        channel = str(backend.channel).strip()
        if not channel:
            raise RuntimeError("channel backend must declare a channel name")
        self._channel_backends[channel] = backend

    def attach_loop_manager(self, loop_manager: Any) -> None:
        """Record the scheduler instance built by bootstrap."""

        self.loop_manager = loop_manager

    def channel_backend(self, channel: str) -> ChannelOutboundBackend:
        """Read one registered backend by channel name."""

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
        """Send a text notification through a channel backend."""

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
        """Send a structured card through a channel backend."""

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
        """Send an image through a channel backend."""

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
        """Update a previously sent external card."""

        return self.channel_backend(channel).update_card(
            card_id=card_id,
            card=card,
            sequence=sequence,
        )

    def ingest_channel_message(self, message: ChannelInboundMessage) -> CoreDispatch:
        """Ingest one normalized channel message."""

        command = parse_control_command(text=message.text, event_key=message.event_key)
        if command is not None:
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

        return self.create_realtime_run(message=message)

    def create_realtime_run(
        self,
        *,
        message: ChannelInboundMessage,
        plan: TaskPlan | None = None,
    ) -> CoreDispatch:
        """Create a realtime Agent run from a normalized user message."""

        plan = plan or _default_realtime_plan()
        agent_request = AgentRunRequest(
            source="realtime",
            conversation_id=message.conversation_id,
            text=message.text,
            suggested_skills=plan.suggested_skills,
            channel=message.channel,
            sender_id=message.sender_id,
            channel_context=message.channel_context(),
            sink_mode="streaming",
        )
        prepared = self.agent_wrapper.prepare(agent_request, plan)
        log.event(
            "realtime dispatch: "
            f"conversation={_short_id(message.conversation_id)}, "
            f"run={prepared.run_id}, "
            f"suggested_skills={','.join(plan.suggested_skills) or 'none'}"
        )
        return CoreDispatch(
            reply_text=plan.ack,
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
        """Create one silent-by-default loop Agent run from runtime.json."""

        runtime = self.runtime_config.read_snapshot()
        loop = _select_loop(runtime.loops, loop_id=loop_id)
        text = loop.prompt or "Run this configured periodic loop. Stay silent unless important."
        suggested_skills = loop.skill_names
        scheduled_at = scheduled_at or utc_now()
        target = _loop_default_target(loop)
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
            suggested_skills=suggested_skills,
            ack=f"Loop run queued: {loop.id}.",
        )
        request = AgentRunRequest(
            source="loop",
            conversation_id=f"daemon:loop:{loop.id}",
            text=text,
            suggested_skills=plan.suggested_skills,
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
            "suggested_skills": list(suggested_skills),
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
        """Delegate an already prepared run to AgentWrapper."""

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
        """Reserved local control-command entrypoint."""

        _ = conversation_id, value
        raise RuntimeError(f"local control command is not configured: {kind}")


def _short_id(value: str) -> str:
    """Compact long ids for logs."""

    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-4:]}"


def _default_realtime_plan() -> TaskPlan:
    """Realtime runs do not preselect skills."""

    return TaskPlan(
        suggested_skills=(),
        ack="收到，我交给 Code Agent 处理。",
    )


def _select_loop(
    loops: tuple[RuntimeLoopConfig, ...],
    *,
    loop_id: str | None,
) -> RuntimeLoopConfig:
    """Select the requested enabled loop or the first enabled loop."""

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
    """Convert a loop default notification target into channel context."""

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
