"""daemon 命令的薄入口，委托 runtime bootstrap 启动完整服务图。"""
from __future__ import annotations

from pkuclaw.config import Settings
from pkuclaw.core import logging as log
from pkuclaw.runtime import run_daemon_runtime


def run_daemon(settings: Settings) -> None:
    """Run the always-online daemon with channels, CoreRuntime, LoopManager, and MCP."""

    log.stage("Starting PkuClaw daemon")
    run_daemon_runtime(settings)
