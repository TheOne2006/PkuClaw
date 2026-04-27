from __future__ import annotations

from dataclasses import dataclass, field

from pkuclaw.core import logging as log
from pkuclaw.core.models import AgentEvent, AgentEventSink


@dataclass
class SilentSink(AgentEventSink):
    """Loop sink: persist/log events without creating channel UI."""

    events: list[AgentEvent] = field(default_factory=list)

    def emit(self, event: AgentEvent) -> None:
        self.events.append(event)
        if event.kind in {"started", "final", "error"}:
            log.event(
                "agent event: "
                f"run={event.run_id}, kind={event.kind}, "
                f"phase={event.phase or 'none'}, message={event.message[:160]}"
            )
