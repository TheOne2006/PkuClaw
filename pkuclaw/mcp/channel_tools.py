"""MCP notification tool result models."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class McpToolResult:
    """Protocol-neutral result returned by MCP notification tool handlers."""

    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
