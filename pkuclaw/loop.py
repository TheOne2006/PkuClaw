from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from pkuclaw.agents import SilentSink
from pkuclaw.config import Settings
from pkuclaw.core import logging as log
from pkuclaw.core.app import CoreRuntime


@dataclass
class LoopManager:
    settings: Settings
    core_runtime: CoreRuntime
    stop_event: threading.Event = field(default_factory=threading.Event)
    next_due_by_loop: dict[str, float] = field(default_factory=dict)

    def tick(self, *, reason: str = "timer", loop_id: str | None = None) -> str:
        dispatch = self.core_runtime.create_loop_run(loop_id=loop_id)
        if dispatch.run_id is None or dispatch.plan is None or dispatch.agent_request is None:
            raise RuntimeError("loop dispatch did not create an agent run")
        loop_label = loop_id or str(dispatch.agent_request.channel_context.get("loop_id") or "default")
        log.stage(f"Loop tick: reason={reason}, loop={loop_label}, run={dispatch.run_id}")
        sink = SilentSink()
        result = self.core_runtime.run_agent(
            dispatch.run_id,
            dispatch.plan,
            dispatch.agent_request,
            sink,
        )
        log.ok(f"Loop run completed: run={result.run_id}, status={result.status}")
        return result.run_id

    def run_forever(self) -> None:
        log.stage("LoopManager started")
        while not self.stop_event.is_set():
            runtime = self.core_runtime.runtime_config.read()
            enabled_loops = [loop for loop in runtime.loops if loop.enabled]
            now = time.monotonic()
            next_wake = now + self.settings.monitor.scan_interval_seconds
            for loop in enabled_loops:
                interval = loop.interval_seconds or self.settings.monitor.scan_interval_seconds
                due_at = self.next_due_by_loop.setdefault(loop.id, now)
                if now >= due_at:
                    try:
                        self.tick(reason="timer", loop_id=loop.id)
                    except Exception as exc:
                        log.fail(f"loop tick failed: loop={loop.id}, error={exc}")
                    self.next_due_by_loop[loop.id] = time.monotonic() + max(1, interval)
                next_wake = min(next_wake, self.next_due_by_loop[loop.id])
            if not enabled_loops:
                log.warn("LoopManager has no enabled loops")
            self.stop_event.wait(max(1, next_wake - time.monotonic()))
