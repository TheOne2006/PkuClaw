from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(help="PKU course monitor and bot control CLI.")
bot_app = typer.Typer(help="Chat bot gateways.")
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
def status() -> None:
    """Print current course status from the local state store."""
    typer.echo("status: state store is not initialized yet")


@app.command()
def sync() -> None:
    """Scan PKU course sources and update local snapshots."""
    typer.echo("sync: collector skeleton is ready, implementation pending")


@app.command()
def daemon() -> None:
    """Run the long-lived monitor loop."""
    typer.echo("daemon: scheduler skeleton is ready, implementation pending")


@bot_app.command("feishu")
def bot_feishu(config: Optional[Path] = typer.Option(None, help="Path to config TOML.")) -> None:
    """Run the Feishu bot gateway."""
    config_hint = f" with config {config}" if config else ""
    typer.echo(f"feishu bot: gateway skeleton is ready{config_hint}")


@app.command()
def pku3b(args: list[str] = typer.Argument(None)) -> None:
    """Proxy a command to the internal pku3b binary."""
    bin_path = Path("crates/pku3b/target/debug/pku3b")
    if not bin_path.exists():
        raise typer.BadParameter("pku3b binary is missing. Run: cargo build --manifest-path crates/pku3b/Cargo.toml")
    subprocess.run([str(bin_path), *(args or [])], check=False)
