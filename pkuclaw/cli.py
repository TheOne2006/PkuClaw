from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

import click
import typer

from pkuclaw.backbone import TeachingBackbone
from pkuclaw.channels.feishu import run_feishu_bot
from pkuclaw.config import load_settings
from pkuclaw.connectors.pku3b import Pku3b
from pkuclaw.core import logging as log
from pkuclaw.core.store import Store
from pkuclaw.runtime_config import RuntimeConfigLoader

app = typer.Typer(help="PkuClaw backend service CLI.")
bot_app = typer.Typer(help="Channel adapters.")
app.add_typer(bot_app, name="bot")


@app.command()
def doctor() -> None:
    """Check local development dependencies."""
    typer.echo("PkuClaw doctor")
    for name in ["python3", "cargo"]:
        found = shutil.which(name)
        typer.echo(f"- {name}: {found or 'not found'}")

    pku3b_src = Path("crates/pku3b")
    typer.echo(f"- pku3b source: {'ok' if pku3b_src.exists() else 'missing'}")
    pku3b_bin = Path("crates/pku3b/target/debug/pku3b")
    typer.echo(f"- pku3b debug bin: {'ok' if pku3b_bin.exists() else 'not built'}")


@app.command()
def status(config: Optional[Path] = typer.Option(None, help="Path to config TOML.")) -> None:
    """Print backend state from the local store."""
    settings = load_settings(config)
    store = Store(settings.app.data_dir / "pkuclaw.db")
    log.startup_table(
        "PkuClaw Status",
        [
            ("config", settings.config_path),
            ("data_dir", settings.app.data_dir),
            ("conversations", store.active_conversation_count()),
        ],
    )
    counts = store.counts_by_status()
    if counts:
        for status_name, count in sorted(counts.items()):
            log.event(f"{status_name}: {count}")
    else:
        log.warn("runs: none")
    recent = store.recent_runs(limit=5)
    for run in recent:
        user_text = " ".join(run.user_text.split())
        log.event(f"{run.run_id} [{run.intent}/{run.status}] {user_text[:60]}")


@app.command()
def sync(config: Optional[Path] = typer.Option(None, help="Path to config TOML.")) -> None:
    """Collect one teaching-network snapshot through pku3b."""
    settings = load_settings(config)
    backbone = TeachingBackbone(
        pku3b=Pku3b(settings.pku3b.bin),
        snapshot_dir=settings.app.data_dir / "snapshots",
    )
    snapshot = backbone.collect_snapshot()
    log.ok(f"teaching snapshot written: {snapshot.path}")


@app.command()
def daemon(config: Optional[Path] = typer.Option(None, help="Path to config TOML.")) -> None:
    """Run the long-lived teaching-network backbone loop."""
    settings = load_settings(config)
    backbone = TeachingBackbone(
        pku3b=Pku3b(settings.pku3b.bin),
        snapshot_dir=settings.app.data_dir / "snapshots",
    )
    runtime_config = RuntimeConfigLoader(settings.app.runtime_config_dir)
    log.stage("Starting teaching backbone daemon")
    while True:
        runtime = runtime_config.read()
        scan_interval = (
            runtime.monitor.scan_interval_seconds
            or settings.monitor.scan_interval_seconds
        )
        log.ok(f"scan interval: {scan_interval}s")
        snapshot = backbone.collect_snapshot()
        log.ok(f"teaching snapshot written: {snapshot.path}")
        time.sleep(scan_interval)


@bot_app.command("feishu")
def bot_feishu(config: Optional[Path] = typer.Option(None, help="Path to config TOML.")) -> None:
    """Run the Feishu bot gateway."""
    try:
        settings = load_settings(config)
        run_feishu_bot(settings)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@app.command()
def pku3b(args: list[str] = typer.Argument(None)) -> None:
    """Proxy a command to the internal pku3b binary."""
    bin_path = Path("crates/pku3b/target/debug/pku3b")
    if not bin_path.exists():
        raise typer.BadParameter(
            "pku3b binary is missing. Run: "
            "cargo build --manifest-path crates/pku3b/Cargo.toml"
        )
    subprocess.run([str(bin_path), *(args or [])], check=False)
