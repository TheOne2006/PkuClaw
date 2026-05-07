"""PkuClaw 命令行入口，负责加载配置并启动 runtime。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
import typer

from pkuclaw.config import load_settings
from pkuclaw.runtime.bootstrap import run_runtime

app = typer.Typer(help="PkuClaw daemon entrypoint.")
realtime_app = typer.Typer(help="Development-only realtime entries.")
app.add_typer(realtime_app, name="realtime")


@app.command()
def daemon(config: Optional[Path] = typer.Option(None, help="Path to config TOML.")) -> None:
    """Run the PkuClaw daemon: channels, CoreRuntime, LoopManager, and notification queue."""
    try:
        # Full daemon mode: user-facing Feishu, scheduled loops, and notification queue.
        run_runtime(load_settings(config), enable_loop=True, enable_notify_queue=True)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@realtime_app.command("feishu")
def realtime_feishu(
    config: Optional[Path] = typer.Option(None, help="Path to config TOML."),
) -> None:
    """Run only the Feishu realtime path for UI/debug work."""
    try:
        # Realtime debug mode keeps CoreRuntime/AgentWrapper but disables
        # autonomous loop ticks and notification queue worker.
        run_runtime(load_settings(config), enable_loop=False, enable_notify_queue=False)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
