from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from pkuclaw.agents import SilentSink
from pkuclaw.config import Settings
from pkuclaw.core import logging as log
from pkuclaw.core.app import CoreLoop


@dataclass
class LoopThread:
    settings: Settings
    core_loop: CoreLoop
    stop_event: threading.Event = field(default_factory=threading.Event)

    def tick(self, *, reason: str = "timer") -> str:
        dispatch = self.core_loop.create_loop_run()
        if dispatch.run_id is None or dispatch.plan is None or dispatch.agent_request is None:
            raise RuntimeError("loop dispatch did not create an agent run")
        log.stage(f"Loop tick: reason={reason}, run={dispatch.run_id}")
        sink = SilentSink()
        result = self.core_loop.run_agent(
            dispatch.run_id,
            dispatch.plan,
            dispatch.agent_request,
            sink,
        )
        log.ok(f"Loop run completed: run={result.run_id}, status={result.status}")
        return result.run_id

    def run_forever(self) -> None:
        log.stage("Loop thread started")
        while not self.stop_event.is_set():
            runtime = self.core_loop.runtime_config.read()
            interval = (
                runtime.loop.interval_seconds
                or self.settings.monitor.scan_interval_seconds
            )
            try:
                self.tick(reason="timer")
            except Exception as exc:
                log.fail(f"loop tick failed: {exc}")
            self.stop_event.wait(max(1, interval))
