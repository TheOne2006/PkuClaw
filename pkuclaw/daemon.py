from __future__ import annotations

from pkuclaw.config import Settings
from pkuclaw.core import logging as log
from pkuclaw.runtime import run_daemon_runtime


def run_daemon(settings: Settings) -> None:
    """Run the always-online daemon with channels, CoreRuntime, LoopManager, and MCP."""

    log.stage("Starting PkuClaw daemon")
    run_daemon_runtime(settings)
