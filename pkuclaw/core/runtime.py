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
from pkuclaw.core.models import (
    AgentEventSink,
    AgentResult,
    AgentRunRequest,
    CoreDispatch,
    TaskPlan,
)
from pkuclaw.core.store import Store, utc_now
from pkuclaw.runtime.config import (
    RuntimeConfigStore,
    RuntimeLoopConfig,
    RuntimeNotificationConfig,
)
from pkuclaw.runtime.events import RuntimeEventSpec, read_event_catalog
from pkuclaw.runtime.skills import OUTBOX_SKILL_NAME


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
        title: str | None = None,
    ) -> ChannelOutboundResult:
        """Send a text notification through a channel backend."""

        target = ChannelTarget(
            channel=channel,
            target_type=target_type,
            target_id=target_id,
        )
        return self.channel_backend(channel).send_text(
            target=target,
            text=text,
            title=title,
        )

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
        caption: str | None = None,
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
            caption=caption,
        )

    def send_channel_file(
        self,
        *,
        channel: str,
        target_type: str,
        target_id: str,
        file_path: str,
        caption: str | None = None,
    ) -> ChannelOutboundResult:
        """Send a file through a channel backend."""

        target = ChannelTarget(
            channel=channel,
            target_type=target_type,
            target_id=target_id,
        )
        return self.channel_backend(channel).send_file(
            target=target,
            file_path=file_path,
            caption=caption,
        )

    def resolve_outbox_target(
        self,
        *,
        run_id: str | None = None,
        loop_id: str | None = None,
    ) -> dict[str, str] | None:
        """Resolve a run target, loop override, or the global default target."""

        if run_id:
            target = _run_outbox_target(self.store.get_run_metadata(run_id))
            if target is not None:
                return target

        runtime = self.runtime_config.read_snapshot()
        if loop_id:
            loop = _select_loop(runtime.loops, loop_id=loop_id)
            return _loop_notification_target(loop, runtime.notifications)
        return _notification_config_target(runtime.notifications)

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
        """Ingest one normalized channel message or PkuClaw quick action event."""

        if message.event_id:
            return self.create_realtime_event_run(message=message, event_id=message.event_id)
        return self.create_realtime_run(message=message)

    def create_realtime_event_run(
        self,
        *,
        message: ChannelInboundMessage,
        event_id: str,
    ) -> CoreDispatch:
        """Create a streaming realtime Agent run from a configured quick action."""

        catalog = read_event_catalog(self.runtime_config.config_dir)
        for warning in catalog.warnings:
            log.warn(warning)
        event = catalog.spec_for(event_id)
        if event is None:
            return CoreDispatch(
                reply_text=f"未知快捷动作：{event_id}",
                channel_target=message.target,
                handled_locally=True,
            )
        normalized = ChannelInboundMessage(
            channel=message.channel,
            conversation_id=message.conversation_id,
            text=event.task,
            sender_id=message.sender_id,
            target=message.target,
            event_id=event.id,
            external_message_id=message.external_message_id,
            raw=message.raw,
            metadata={
                **dict(message.metadata),
                "trigger": "runtime_event",
                "event_id": event.id,
                "event_title": event.title,
            },
        )
        return self.create_realtime_run(
            message=normalized,
            plan=_event_realtime_plan(event),
        )

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
        suggested_skills = _loop_suggested_skills(loop.suggested_skills)
        scheduled_at = scheduled_at or utc_now()
        target = _loop_notification_target(loop, runtime.notifications)
        channel_context: dict[str, Any] = {
            "loop_id": loop.id,
            "notify_policy": runtime.notifications.policy,
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
            channel=target["channel"] if target is not None else None,
            sender_id=None,
            channel_context=channel_context,
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
        """Delegate an already prepared run to AgentWrapper."""

        return self.agent_wrapper.run(
            run_id=run_id,
            request=request,
            plan=plan,
            sink=sink,
        )


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


def _event_realtime_plan(event: RuntimeEventSpec) -> TaskPlan:
    """Build the fixed realtime plan for a configured quick action."""

    return TaskPlan(
        suggested_skills=event.suggested_skills,
        ack=event.ack,
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


def _loop_suggested_skills(suggested_skills: tuple[str, ...]) -> tuple[str, ...]:
    """Append the channel outbox skill to every loop run."""

    if OUTBOX_SKILL_NAME in suggested_skills:
        return suggested_skills
    return (*suggested_skills, OUTBOX_SKILL_NAME)


def _run_outbox_target(metadata: dict[str, Any]) -> dict[str, str] | None:
    """Extract the original channel target from run metadata."""

    channel = metadata.get("channel")
    if not isinstance(channel, dict):
        return None
    target = channel.get("target")
    if not isinstance(target, dict):
        return None
    raw_channel = target.get("channel")
    target_type = target.get("target_type")
    target_id = target.get("target_id")
    if (
        isinstance(raw_channel, str)
        and raw_channel.strip()
        and isinstance(target_type, str)
        and target_type.strip()
        and isinstance(target_id, str)
        and target_id.strip()
    ):
        return {
            "channel": raw_channel.strip(),
            "target_type": target_type.strip(),
            "target_id": target_id.strip(),
        }
    return None


def _loop_notification_target(
    loop: RuntimeLoopConfig,
    notifications: RuntimeNotificationConfig,
) -> dict[str, str] | None:
    """Return loop-specific notification target or the global default target."""

    if (
        loop.default_channel
        and loop.default_target_type
        and loop.default_target_id
    ):
        return {
            "channel": loop.default_channel,
            "target_type": loop.default_target_type,
            "target_id": loop.default_target_id,
        }
    return _notification_config_target(notifications)


def _notification_config_target(
    notifications: RuntimeNotificationConfig,
) -> dict[str, str] | None:
    """Convert the global default notification target into channel context."""

    if (
        notifications.default_channel
        and notifications.default_target_type
        and notifications.default_target_id
    ):
        return {
            "channel": notifications.default_channel,
            "target_type": notifications.default_target_type,
            "target_id": notifications.default_target_id,
        }
    return None
