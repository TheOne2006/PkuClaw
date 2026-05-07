"""构建 Store、RuntimeConfigStore、CoreRuntime、Feishu、通知队列和 LoopManager。"""
from __future__ import annotations

from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, field
import threading
from pathlib import Path

from pkuclaw.agents.wrapper import AgentWrapper
from pkuclaw.channels.feishu.gateway import FeishuRealtimeGateway, build_feishu_realtime_gateway
from pkuclaw.config import Settings, resolve_notify_queue_dir
from pkuclaw.core import logging as log
from pkuclaw.core.runtime import CoreRuntime
from pkuclaw.core.store import Store
from pkuclaw.core.loops import LoopManager
from pkuclaw.notify_queue.worker import NotifyQueueWorker
from pkuclaw.runtime.config import RuntimeConfigStore


@dataclass(frozen=True)
class CoreRuntimeServices:
    """Objects owned by daemon/runtime bootstrap before channels are started."""

    settings: Settings
    store: Store
    runtime_config: RuntimeConfigStore
    agent_wrapper: AgentWrapper
    core_runtime: CoreRuntime
    run_executor: Executor
    callback_executor: Executor


@dataclass(frozen=True)
class RuntimeBootstrap:
    """Started runtime components around the CoreRuntime control plane."""

    services: CoreRuntimeServices
    feishu_gateway: FeishuRealtimeGateway
    loop_manager: LoopManager | None = None
    notify_queue_worker: NotifyQueueWorker | None = None
    threads: tuple[threading.Thread, ...] = field(default_factory=tuple)


def run_runtime(
    settings: Settings,
    *,
    enable_loop: bool,
    enable_notify_queue: bool,
) -> None:
    """Build the daemon runtime graph, then block on the Feishu channel adapter."""

    bootstrap = build_runtime_bootstrap(
        settings,
        enable_loop=enable_loop,
        enable_notify_queue=enable_notify_queue,
    )
    bootstrap.feishu_gateway.start()


def build_runtime_bootstrap(
    settings: Settings,
    *,
    enable_loop: bool,
    enable_notify_queue: bool,
) -> RuntimeBootstrap:
    """Build CoreRuntime, register Feishu, optionally start notify queue/LoopManager."""

    _log_runtime(
        settings,
        enable_loop=enable_loop,
        enable_notify_queue=enable_notify_queue,
    )
    services = build_core_runtime_services(settings)
    feishu_gateway = build_feishu_realtime_gateway(
        settings=settings,
        core_runtime=services.core_runtime,
        run_executor=services.run_executor,
        callback_executor=services.callback_executor,
    )
    services.core_runtime.register_channel_backend(feishu_gateway.channel_backend)
    log.ok("Feishu channel registered with CoreRuntime outbox registry")

    threads: list[threading.Thread] = []
    notify_queue_worker: NotifyQueueWorker | None = None
    if enable_notify_queue:
        notify_queue_worker, thread = _start_notify_queue_thread(
            settings=settings,
            core_runtime=services.core_runtime,
            default_channel=feishu_gateway.channel,
        )
        threads.append(thread)

    loop_manager: LoopManager | None = None
    if enable_loop:
        loop_manager, thread = _start_loop_manager(
            settings=settings,
            core_runtime=services.core_runtime,
        )
        threads.append(thread)

    return RuntimeBootstrap(
        services=services,
        feishu_gateway=feishu_gateway,
        loop_manager=loop_manager,
        notify_queue_worker=notify_queue_worker,
        threads=tuple(threads),
    )


def build_core_runtime_services(
    settings: Settings,
    *,
    repo_root: Path | None = None,
) -> CoreRuntimeServices:
    """Construct daemon-owned Store/config/wrapper/CoreRuntime/executors."""

    runtime_config = RuntimeConfigStore(settings.app.runtime_config_dir)
    store = _open_store(settings, runtime_config=runtime_config)
    agent_wrapper = AgentWrapper(
        settings=settings,
        store=store,
        runtime_config=runtime_config,
        repo_root=repo_root,
    )
    run_executor = ThreadPoolExecutor(max_workers=settings.codex.max_concurrent_runs)
    callback_executor = ThreadPoolExecutor(max_workers=2)
    core_runtime = CoreRuntime(
        store=store,
        agent_wrapper=agent_wrapper,
        runtime_config=runtime_config,
        run_executor=run_executor,
    )
    log.ok(
        "CoreRuntime ready: Store + RuntimeConfigStore + AgentWrapper + executor"
    )
    log.ok(f"Agent worker pool ready: max_workers={settings.codex.max_concurrent_runs}")
    return CoreRuntimeServices(
        settings=settings,
        store=store,
        runtime_config=runtime_config,
        agent_wrapper=agent_wrapper,
        core_runtime=core_runtime,
        run_executor=run_executor,
        callback_executor=callback_executor,
    )


def _start_loop_manager(
    *,
    settings: Settings,
    core_runtime: CoreRuntime,
) -> tuple[LoopManager, threading.Thread]:
    """创建 LoopManager 并在 daemon 线程中启动。"""
    loop_manager = LoopManager(settings=settings, core_runtime=core_runtime)
    core_runtime.attach_loop_manager(loop_manager)
    thread = threading.Thread(
        target=loop_manager.run_forever,
        name="pkuclaw-loop-manager",
        daemon=True,
    )
    thread.start()
    log.ok("LoopManager started by runtime bootstrap")
    return loop_manager, thread


def _start_notify_queue_thread(
    *,
    settings: Settings,
    core_runtime: CoreRuntime,
    default_channel: str,
) -> tuple[NotifyQueueWorker, threading.Thread]:
    """创建 NotifyQueueWorker 并在 daemon 线程中启动。"""

    queue_dir = resolve_notify_queue_dir(settings)
    worker = NotifyQueueWorker(
        queue_dir=queue_dir,
        scan_interval_seconds=settings.notify_queue.scan_interval_seconds,
        core_runtime=core_runtime,
        default_channel=default_channel,
    )
    thread = threading.Thread(
        target=worker.serve_forever,
        name="pkuclaw-notify-queue",
        daemon=True,
    )
    thread.start()
    log.ok(
        "Notification queue worker started: "
        f"{queue_dir} (scan={settings.notify_queue.scan_interval_seconds}s)"
    )
    return worker, thread


def _open_store(settings: Settings, *, runtime_config: RuntimeConfigStore) -> Store:
    """打开 SQLite Store 并输出当前状态摘要。"""
    log.stage("Opening local state store")
    store = Store(
        settings.app.data_dir / "pkuclaw.db",
        default_agent_settings=runtime_config.read_snapshot().agent,
    )
    log.ok(
        "State store ready: "
        f"conversations={store.active_conversation_count()}, "
        f"runs={sum(store.counts_by_status().values())}"
    )
    return store


def _log_runtime(
    settings: Settings,
    *,
    enable_loop: bool,
    enable_notify_queue: bool,
) -> None:
    """输出 runtime bootstrap 的启动配置摘要。"""
    log.stage("Booting PkuClaw runtime")
    log.startup_table(
        "Runtime",
        [
            ("config", settings.config_path),
            ("data_dir", settings.app.data_dir),
            ("runtime_config_dir", settings.app.runtime_config_dir),
            ("agent", settings.agent.provider),
            ("codex_bin", settings.codex.bin),
            ("codex_sandbox", settings.codex.sandbox),
            ("codex_timeout", f"{settings.codex.timeout_seconds}s"),
            ("max_workers", settings.codex.max_concurrent_runs),
            ("notify_queue", "enabled" if enable_notify_queue else "disabled"),
            ("loop_manager", "enabled" if enable_loop else "disabled"),
        ],
    )
