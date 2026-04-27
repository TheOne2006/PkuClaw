from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table


console = Console(highlight=False)


def stage(message: str) -> None:
    console.print(f"[bold cyan]▶[/bold cyan] {message}")


def ok(message: str) -> None:
    console.print(f"[bold green]✓[/bold green] {message}")


def warn(message: str) -> None:
    console.print(f"[bold yellow]![/bold yellow] {message}")


def fail(message: str) -> None:
    console.print(f"[bold red]✗[/bold red] {message}")


def event(message: str) -> None:
    console.print(f"[bold magenta]◆[/bold magenta] {message}")


def path_text(path: str | Path) -> str:
    return f"[dim]{path}[/dim]"


def startup_table(title: str, rows: list[tuple[str, Any]]) -> None:
    table = Table(title=title, show_header=False, box=None, padding=(0, 1))
    table.add_column("key", style="cyan")
    table.add_column("value")
    for key, value in rows:
        table.add_row(key, str(value))
    console.print(table)
