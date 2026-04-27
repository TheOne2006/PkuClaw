from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

from pkuclaw.agents import AgentWrapper
from pkuclaw.config import Settings
from pkuclaw.core import logging as log
from pkuclaw.core.app import CoreLoop
from pkuclaw.core.store import Store
from pkuclaw.loop import LoopThread
from pkuclaw.mcp import ChannelToolServer
from pkuclaw.runtime_config import RuntimeConfigLoader

from .cards import FeishuCardRenderer
from .handlers import FeishuEventHandlers
from .sdk import (
    build_api_client,
    build_cardkit_client,
    build_event_handler,
    load_feishu_sdk,
    new_ws_client,
)
from .tools import FeishuChannelToolBackend


def run_feishu_bot(
    settings: Settings,
    *,
    enable_loop: bool = False,
    enable_mcp: bool = False,
) -> None:
    """Start the Feishu websocket bot and reply to text messages."""
    _log_runtime(settings)
    _require_websocket_mode(settings)

    log.stage("Loading Feishu SDK")
    sdk = load_feishu_sdk()
    log.ok("Feishu SDK loaded")

    log.stage("Resolving Feishu credentials")
    app_secret = settings.feishu.resolve_app_secret()
    log.ok("Feishu credentials resolved")

    log.stage("Building Feishu API client")
    api_client = build_api_client(
        sdk=sdk,
        settings=settings,
        app_secret=app_secret,
    )
    message_client = build_cardkit_client(sdk=sdk, api_client=api_client)
    card_renderer = FeishuCardRenderer()
    log.ok("Feishu API client ready")

    store = _open_store(settings)
    core_loop = _build_core_loop(settings=settings, store=store)
    executor = ThreadPoolExecutor(max_workers=settings.codex.max_concurrent_runs)
    callback_executor = ThreadPoolExecutor(max_workers=2)
    log.ok(f"Agent worker pool ready: max_workers={settings.codex.max_concurrent_runs}")
    if enable_mcp:
        _start_mcp_thread(
            settings=settings,
            message_client=message_client,
            card_renderer=card_renderer,
        )
    if enable_loop:
        _start_loop_thread(settings=settings, core_loop=core_loop)

    handlers = FeishuEventHandlers(
        settings=settings,
        core_loop=core_loop,
        message_client=message_client,
        card_renderer=card_renderer,
        card_action_response_cls=sdk.card_action_response,
        executor=executor,
        callback_executor=callback_executor,
    )
    event_handler = build_event_handler(sdk=sdk, handlers=handlers)
    log.ok(
        "Feishu event handlers registered: "
        "message_receive, bot_menu, card_action, message_read(no-op)"
    )

    log.stage("Connecting Feishu websocket")
    client = new_ws_client(
        sdk=sdk,
        app_id=settings.feishu.app_id,
        app_secret=app_secret,
        event_handler=event_handler,
        domain=settings.feishu.api_base,
    )
    log.ok("Startup complete; waiting for Feishu messages")
    client.start()


def _start_loop_thread(*, settings: Settings, core_loop: CoreLoop) -> None:
    loop_thread = LoopThread(settings=settings, core_loop=core_loop)
    thread = threading.Thread(
        target=loop_thread.run_forever,
        name="pkuclaw-loop",
        daemon=True,
    )
    thread.start()
    log.ok("Loop thread started")


def _start_mcp_thread(
    *,
    settings: Settings,
    message_client: object,
    card_renderer: FeishuCardRenderer,
) -> None:
    backend = FeishuChannelToolBackend(
        client=message_client,  # type: ignore[arg-type]
        renderer=card_renderer,
    )
    server = ChannelToolServer(
        host=settings.mcp.host,
        port=settings.mcp.port,
        backend=backend,
    )
    thread = threading.Thread(
        target=server.serve_forever,
        name="pkuclaw-mcp",
        daemon=True,
    )
    thread.start()
    log.ok(f"MCP server thread started: {settings.mcp.host}:{settings.mcp.port}")


def _log_runtime(settings: Settings) -> None:
    log.stage("Booting PkuClaw Feishu gateway")
    log.startup_table(
        "Runtime",
        [
            ("config", settings.config_path),
            ("data_dir", settings.app.data_dir),
            ("runtime_config_dir", settings.app.runtime_config_dir),
            ("feishu_mode", settings.feishu.event_mode),
            ("feishu_app_id", settings.feishu.app_id),
            ("agent", settings.agent.provider),
            ("codex_bin", settings.codex.bin),
            ("codex_sandbox", settings.codex.sandbox),
            ("codex_timeout", f"{settings.codex.timeout_seconds}s"),
            ("max_workers", settings.codex.max_concurrent_runs),
        ],
    )


def _require_websocket_mode(settings: Settings) -> None:
    if settings.feishu.event_mode == "websocket":
        return
    raise RuntimeError(f"unsupported Feishu event mode: {settings.feishu.event_mode}")


def _open_store(settings: Settings) -> Store:
    log.stage("Opening local state store")
    store = Store(settings.app.data_dir / "pkuclaw.db")
    log.ok(
        "State store ready: "
        f"conversations={store.active_conversation_count()}, "
        f"runs={sum(store.counts_by_status().values())}"
    )
    return store


def _build_core_loop(*, settings: Settings, store: Store) -> CoreLoop:
    log.stage("Building realtime runtime")
    runtime_config = RuntimeConfigLoader(settings.app.runtime_config_dir)
    agent_wrapper = AgentWrapper(
        settings=settings,
        store=store,
        runtime_config=runtime_config,
    )
    core_loop = CoreLoop(
        store=store,
        agent_wrapper=agent_wrapper,
        runtime_config=runtime_config,
    )
    log.ok("Realtime runtime ready: channel -> Agent-Wrapper -> Agent")
    return core_loop
