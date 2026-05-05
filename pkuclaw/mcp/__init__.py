"""daemon MCP 包导出，使用懒加载避免 CoreRuntime 相关循环导入。"""
from __future__ import annotations

from pkuclaw.mcp.channel_tools import McpToolResult
from pkuclaw.mcp.schemas import TOOL_REGISTRY, list_tool_schemas, render_tool_prompt

__all__ = [
    "DaemonMcpServer",
    "DaemonMcpToolHandler",
    "McpToolResult",
    "TOOL_REGISTRY",
    "handle_mcp_request",
    "list_tool_schemas",
    "render_tool_prompt",
]


def __getattr__(name: str) -> object:
    """Lazily expose CoreRuntime-dependent MCP classes without import cycles."""

    if name == "DaemonMcpServer":
        from pkuclaw.mcp.server import DaemonMcpServer

        return DaemonMcpServer
    if name == "handle_mcp_request":
        from pkuclaw.mcp.server import handle_mcp_request

        return handle_mcp_request
    if name == "DaemonMcpToolHandler":
        from pkuclaw.mcp.handlers import DaemonMcpToolHandler

        return DaemonMcpToolHandler
    raise AttributeError(name)
