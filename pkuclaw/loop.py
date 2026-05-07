"""LoopManager 调度热加载的周期任务，并通过 CoreRuntime 创建 loop run。"""
from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

from pkuclaw.agents.sinks import SilentSink
from pkuclaw.config import Settings
from pkuclaw.core import logging as log
from pkuclaw.core.app import CoreRuntime
from pkuclaw.core.models import CoreDispatch
from pkuclaw.core.store import utc_now
from pkuclaw.runtime_config import RuntimeLoopConfig


@dataclass(frozen=True)
class ScheduledLoopRun:
    """LoopManager 已提交到 executor 的一次 loop run。"""
    loop_id: str
    run_id: str
    future: Future[str]


@dataclass
class LoopManager:
    """CoreRuntime-owned, business-logic-free scheduler for runtime loop specs."""

    settings: Settings
    core_runtime: CoreRuntime
    stop_event: threading.Event = field(default_factory=threading.Event)
    next_due_by_loop: dict[str, float] = field(default_factory=dict)
    executor: ThreadPoolExecutor | None = None
    _owns_executor: bool = field(default=False, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _active_by_loop: dict[str, int] = field(default_factory=dict, init=False)
    _futures_by_loop: dict[str, set[Future[str]]] = field(
        default_factory=dict,
        init=False,
    )

    def __post_init__(self) -> None:
        if self.executor is not None:
            return
        max_workers = max(2, int(self.settings.codex.max_concurrent_runs or 1))
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="pkuclaw-loop-run",
        )
        self._owns_executor = True

    def tick(
        self,
        *,
        reason: str = "manual",
        loop_id: str | None = None,
        wait: bool = True,
    ) -> str:
        """Manually schedule one enabled loop and optionally wait for completion."""

        runtime = self.core_runtime.runtime_config.read_snapshot()
        loop = _select_enabled_loop(runtime.loops, loop_id=loop_id)
        scheduled = self._submit_loop(
            loop,
            reason=reason,
            scheduled_at=utc_now(),
        )
        if scheduled is None:
            raise RuntimeError(f"runtime loop already running: {loop.id}")
        if wait:
            scheduled.future.result()
        return scheduled.run_id

    def run_due_once(
        self,
        *,
        reason: str = "timer",
        now: float | None = None,
    ) -> tuple[str, ...]:
        """Hot-load loop specs once and submit every due enabled loop."""

        runtime = self.core_runtime.runtime_config.read_snapshot()
        enabled_loops = [loop for loop in runtime.loops if loop.enabled]
        self._prune_loop_state({loop.id for loop in enabled_loops})
        if not enabled_loops:
            log.warn("LoopManager has no enabled loops")
            return ()

        current = time.monotonic() if now is None else now
        scheduled_run_ids: list[str] = []
        for loop in enabled_loops:
            interval = _loop_interval_seconds(
                loop,
                fallback=self.settings.monitor.scan_interval_seconds,
            )
            # First sighting is immediately due; later passes use monotonic time
            # so wall-clock changes do not shift scheduler cadence.
            due_at = self.next_due_by_loop.setdefault(loop.id, current)
            if current < due_at:
                continue
            try:
                scheduled = self._submit_loop(
                    loop,
                    reason=reason,
                    scheduled_at=utc_now(),
                )
                if scheduled is not None:
                    scheduled_run_ids.append(scheduled.run_id)
            except Exception as exc:
                log.fail(f"loop tick failed: loop={loop.id}, error={exc}")
            finally:
                self.next_due_by_loop[loop.id] = current + interval
        return tuple(scheduled_run_ids)

    def run_forever(self) -> None:
        """循环运行定时调度，直到 stop_event 被设置。"""
        log.stage("LoopManager started")
        while not self.stop_event.is_set():
            now = time.monotonic()
            try:
                self.run_due_once(reason="timer", now=now)
            except Exception as exc:
                log.fail(f"LoopManager scheduler pass failed: error={exc}")
            next_wake = min(
                self.next_due_by_loop.values(),
                default=now + self.settings.monitor.scan_interval_seconds,
            )
            self.stop_event.wait(max(1, next_wake - time.monotonic()))

    def shutdown(self, *, wait: bool = True) -> None:
        """停止调度器，并在拥有 executor 时关闭 worker pool。"""
        self.stop_event.set()
        if self._owns_executor and self.executor is not None:
            self.executor.shutdown(wait=wait, cancel_futures=True)

    def _submit_loop(
        self,
        loop: RuntimeLoopConfig,
        *,
        reason: str,
        scheduled_at: str,
    ) -> ScheduledLoopRun | None:
        """为单个 loop 预留并发槽、创建 run、提交后台执行。"""
        if not self._reserve_loop_slot(loop):
            log.warn(f"loop run skipped because overlap is prevented: loop={loop.id}")
            return None
        try:
            # Reserve before creating the Store run to avoid queuing duplicates
            # when prevent_overlap/max_concurrent_runs says the loop is full.
            dispatch = self.core_runtime.create_loop_run(
                loop_id=loop.id,
                scheduled_at=scheduled_at,
            )
            _ensure_dispatch_ready(dispatch, loop_id=loop.id)
            future = self._executor().submit(
                self._run_dispatch,
                loop.id,
                dispatch,
                reason,
            )
        except Exception:
            self._release_loop_slot(loop.id)
            raise

        with self._lock:
            self._futures_by_loop.setdefault(loop.id, set()).add(future)
        future.add_done_callback(
            lambda completed, loop_id=loop.id: self._finish_loop_run(
                loop_id,
                completed,
            )
        )
        log.stage(
            "Loop run scheduled: "
            f"reason={reason}, loop={loop.id}, run={dispatch.run_id}"
        )
        return ScheduledLoopRun(
            loop_id=loop.id,
            run_id=str(dispatch.run_id),
            future=future,
        )

    def _run_dispatch(
        self,
        loop_id: str,
        dispatch: CoreDispatch,
        reason: str,
    ) -> str:
        """在 worker 线程中用 SilentSink 执行 loop dispatch。"""
        if dispatch.run_id is None or dispatch.plan is None or dispatch.agent_request is None:
            raise RuntimeError("loop dispatch did not create an agent run")
        log.stage(f"Loop run starting: reason={reason}, loop={loop_id}, run={dispatch.run_id}")
        sink = SilentSink()
        result = self.core_runtime.run_agent(
            dispatch.run_id,
            dispatch.plan,
            dispatch.agent_request,
            sink,
        )
        log.ok(f"Loop run completed: run={result.run_id}, status={result.status}")
        return result.run_id

    def _reserve_loop_slot(self, loop: RuntimeLoopConfig) -> bool:
        """内部辅助函数，封装 reserve loop slot 逻辑。"""
        limit = _loop_concurrency_limit(loop)
        with self._lock:
            active = self._active_by_loop.get(loop.id, 0)
            if active >= limit:
                return False
            self._active_by_loop[loop.id] = active + 1
            return True

    def _release_loop_slot(self, loop_id: str) -> None:
        """内部辅助函数，封装 release loop slot 逻辑。"""
        with self._lock:
            active = self._active_by_loop.get(loop_id, 0) - 1
            if active > 0:
                self._active_by_loop[loop_id] = active
            else:
                self._active_by_loop.pop(loop_id, None)

    def _finish_loop_run(self, loop_id: str, future: Future[str]) -> None:
        """内部辅助函数，封装 finish loop run 逻辑。"""
        with self._lock:
            futures = self._futures_by_loop.get(loop_id)
            if futures is not None:
                futures.discard(future)
                if not futures:
                    self._futures_by_loop.pop(loop_id, None)
        self._release_loop_slot(loop_id)
        try:
            future.result()
        except Exception as exc:
            log.fail(f"Loop run failed: loop={loop_id}, error={exc}")

    def _prune_loop_state(self, enabled_loop_ids: set[str]) -> None:
        """内部辅助函数，封装 prune loop state 逻辑。"""
        with self._lock:
            for loop_id in list(self.next_due_by_loop):
                if loop_id not in enabled_loop_ids:
                    self.next_due_by_loop.pop(loop_id, None)
            for loop_id in list(self._active_by_loop):
                if loop_id not in enabled_loop_ids and not self._futures_by_loop.get(loop_id):
                    self._active_by_loop.pop(loop_id, None)

    def _executor(self) -> ThreadPoolExecutor:
        """内部辅助函数，封装 executor 逻辑。"""
        if self.executor is None:
            raise RuntimeError("LoopManager executor is not configured")
        return self.executor


def _ensure_dispatch_ready(dispatch: CoreDispatch, *, loop_id: str) -> None:
    """确认 loop dispatch 具备运行 Agent 所需字段。"""
    if dispatch.run_id is None or dispatch.plan is None or dispatch.agent_request is None:
        raise RuntimeError(f"loop dispatch did not create an agent run: {loop_id}")


def _select_enabled_loop(
    loops: tuple[RuntimeLoopConfig, ...],
    *,
    loop_id: str | None,
) -> RuntimeLoopConfig:
    """选择指定 enabled loop 或第一个 enabled loop。"""
    if loop_id is not None:
        for loop in loops:
            if loop.id != loop_id:
                continue
            if not loop.enabled:
                raise RuntimeError(f"runtime loop disabled: {loop_id}")
            return loop
        raise RuntimeError(f"runtime loop not found: {loop_id}")
    for loop in loops:
        if loop.enabled:
            return loop
    raise RuntimeError("no enabled runtime loops")


def _loop_interval_seconds(loop: RuntimeLoopConfig, *, fallback: int) -> int:
    """计算 loop 调度间隔，并用启动配置兜底。"""
    return max(1, int(loop.interval_seconds or fallback or 1))


def _loop_concurrency_limit(loop: RuntimeLoopConfig) -> int:
    """根据 prevent_overlap/max_concurrent_runs 计算并发上限。"""
    if loop.prevent_overlap:
        return 1
    return max(1, int(loop.max_concurrent_runs or 1))
