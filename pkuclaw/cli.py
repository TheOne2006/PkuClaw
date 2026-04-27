from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
import typer

from pkuclaw.channels.feishu import run_feishu_bot
from pkuclaw.config import load_settings
from pkuclaw.daemon import run_daemon

app = typer.Typer(help="PkuClaw daemon entrypoint.")
realtime_app = typer.Typer(help="Development-only realtime entries.")
app.add_typer(realtime_app, name="realtime")


@app.command()
def daemon(config: Optional[Path] = typer.Option(None, help="Path to config TOML.")) -> None:
    """Run the PkuClaw daemon: realtime thread, loop thread, and MCP server."""
    try:
        run_daemon(load_settings(config))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@realtime_app.command("feishu")
def realtime_feishu(
    config: Optional[Path] = typer.Option(None, help="Path to config TOML."),
) -> None:
    """Run only the Feishu realtime thread for UI/debug work."""
    try:
        run_feishu_bot(load_settings(config), enable_loop=False, enable_mcp=False)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
