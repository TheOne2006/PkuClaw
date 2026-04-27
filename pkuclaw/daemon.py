from __future__ import annotations

from pkuclaw.channels.feishu import run_feishu_bot
from pkuclaw.config import Settings
from pkuclaw.core import logging as log


def run_daemon(settings: Settings) -> None:
    """Run the always-online daemon with realtime, loop, and MCP threads."""

    log.stage("Starting PkuClaw daemon")
    run_feishu_bot(settings, enable_loop=True, enable_mcp=True)
