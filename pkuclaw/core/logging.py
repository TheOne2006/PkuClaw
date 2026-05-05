"""基于 rich 的简洁 runtime 日志输出工具。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table


console = Console(highlight=False)


def stage(message: str) -> None:
    """输出一个阶段开始日志。"""
    console.print(f"[bold cyan]▶[/bold cyan] {message}")


def ok(message: str) -> None:
    """输出一个成功日志。"""
    console.print(f"[bold green]✓[/bold green] {message}")


def warn(message: str) -> None:
    """输出一个警告日志。"""
    console.print(f"[bold yellow]![/bold yellow] {message}")


def fail(message: str) -> None:
    """把当前 sink 置为失败态并展示错误。"""
    console.print(f"[bold red]✗[/bold red] {message}")


def event(message: str) -> None:
    """输出一个普通事件日志。"""
    console.print(f"[bold magenta]◆[/bold magenta] {message}")


def path_text(path: str | Path) -> str:
    """把路径包装成 rich 的 dim 样式文本。"""
    return f"[dim]{path}[/dim]"


def startup_table(title: str, rows: list[tuple[str, Any]]) -> None:
    """用 rich 表格输出启动配置摘要。"""
    table = Table(title=title, show_header=False, box=None, padding=(0, 1))
    table.add_column("key", style="cyan")
    table.add_column("value")
    for key, value in rows:
        table.add_row(key, str(value))
    console.print(table)
