"""daemon MCP 工具 schema 注册表和 prompt 文档渲染器。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


JsonSchema = dict[str, Any]


@dataclass(frozen=True)
class ToolSchema:
    """daemon MCP 工具名称、说明、输入 schema 和分类。"""
    name: str
    description: str
    input_schema: JsonSchema
    category: str
    unsupported: bool = False

    def as_mcp_tool(self) -> dict[str, Any]:
        """转换成 MCP tools/list 需要的 JSON schema 对象。"""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def list_tool_schemas() -> list[dict[str, Any]]:
    """Return JSON-serializable MCP tool schema objects."""

    return [tool.as_mcp_tool() for tool in TOOL_REGISTRY]


def render_tool_prompt() -> str:
    """Render concise agent-facing daemon MCP documentation from the registry."""

    lines = [
        (
            "Daemon MCP is the internal Agent -> CoreRuntime control surface. "
            "Use these tools through the configured `pkuclaw_daemon` MCP server; "
            "normal realtime replies are already streamed by the active channel."
        ),
        "",
    ]
    categories = (
        ("channel", "Channel outbox tools"),
        ("runtime_read", "Runtime read tools"),
        ("runtime_write", "Runtime write tools"),
    )
    by_name = {tool.name: tool for tool in TOOL_REGISTRY}
    for category, title in categories:
        items = [tool for tool in TOOL_REGISTRY if tool.category == category]
        if not items:
            continue
        lines.append(f"### {title}")
        for tool in items:
            required = _required_args(tool.input_schema)
            required_text = f"; required: {', '.join(required)}" if required else ""
            unsupported_text = " (currently returns unsupported)" if tool.unsupported else ""
            lines.append(
                f"- `{tool.name}`{required_text}: {tool.description}{unsupported_text}"
            )
        lines.append("")
    if any(tool.unsupported for tool in by_name.values()):
        lines.append(
            "Runtime write tools are exposed for discoverability but are disabled "
            "until the safe config write/backup/audit phase lands."
        )
    return "\n".join(lines).strip()


def _required_args(schema: Mapping[str, Any]) -> tuple[str, ...]:
    """从 JSON schema 中提取 required 参数名。"""
    value = schema.get("required", ())
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


_EMPTY_OBJECT: JsonSchema = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


TOOL_REGISTRY: tuple[ToolSchema, ...] = (
    ToolSchema(
        name="channel_send_text",
        description="Send a text notification through CoreRuntime's channel outbox.",
        category="channel",
        input_schema={
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Optional channel name; defaults to the MCP server channel.",
                },
                "target_id": {"type": "string"},
                "target_type": {"type": "string", "default": "chat_id"},
                "text": {"type": "string"},
            },
            "required": ["target_id", "text"],
        },
    ),
    ToolSchema(
        name="channel_send_card",
        description="Send a structured card through CoreRuntime's channel outbox.",
        category="channel",
        input_schema={
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Optional channel name; defaults to the MCP server channel.",
                },
                "target_id": {"type": "string"},
                "target_type": {"type": "string", "default": "chat_id"},
                "card": {"type": "object"},
            },
            "required": ["target_id", "card"],
        },
    ),
    ToolSchema(
        name="channel_send_image",
        description="Send an image through CoreRuntime's channel outbox.",
        category="channel",
        input_schema={
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Optional channel name; defaults to the MCP server channel.",
                },
                "target_id": {"type": "string"},
                "target_type": {"type": "string", "default": "chat_id"},
                "image_path": {"type": "string"},
            },
            "required": ["target_id", "image_path"],
        },
    ),
    ToolSchema(
        name="channel_update_card",
        description="Update a previously sent card through CoreRuntime's channel outbox.",
        category="channel",
        input_schema={
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Optional channel name; defaults to the MCP server channel.",
                },
                "card_id": {"type": "string"},
                "card": {"type": "object"},
                "sequence": {"type": "integer"},
            },
            "required": ["card_id", "card", "sequence"],
        },
    ),
    ToolSchema(
        name="runtime_get_status",
        description="Read daemon status, registered channels, run counts, and active runtime settings.",
        category="runtime_read",
        input_schema={
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "Optional conversation/thread key for merged agent settings.",
                }
            },
        },
    ),
    ToolSchema(
        name="runtime_get_config",
        description="Read the current hot-loaded runtime config snapshot and warnings.",
        category="runtime_read",
        input_schema=_EMPTY_OBJECT,
    ),
    ToolSchema(
        name="runtime_list_loops",
        description="List hot-loaded loop specs known to CoreRuntime.",
        category="runtime_read",
        input_schema=_EMPTY_OBJECT,
    ),
    ToolSchema(
        name="runtime_list_recent_runs",
        description="List recent runs from CoreRuntime's store.",
        category="runtime_read",
        input_schema={
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
        },
    ),
    ToolSchema(
        name="runtime_get_run",
        description="Read one run record and metadata from CoreRuntime's store.",
        category="runtime_read",
        input_schema={
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
    ),
    ToolSchema(
        name="runtime_add_loop",
        description="Add a runtime loop spec after validation, backup, and audit.",
        category="runtime_write",
        input_schema={
            "type": "object",
            "properties": {
                "loop": {
                    "type": "object",
                    "description": "Loop spec with id, enabled, interval_seconds, prompt, skill_names, sink_mode, notify_policy.",
                },
                "actor": {"type": "string", "description": "Optional audit actor label."},
                "run_id": {"type": "string", "description": "Optional originating run id."},
            },
            "required": ["loop"],
        },
    ),
    ToolSchema(
        name="runtime_update_loop",
        description="Update a runtime loop spec after validation, backup, and audit.",
        category="runtime_write",
        input_schema={
            "type": "object",
            "properties": {
                "loop_id": {"type": "string"},
                "updates": {"type": "object"},
                "actor": {"type": "string", "description": "Optional audit actor label."},
                "run_id": {"type": "string", "description": "Optional originating run id."},
            },
            "required": ["loop_id", "updates"],
        },
    ),
    ToolSchema(
        name="runtime_enable_loop",
        description="Enable a runtime loop spec after validation, backup, and audit.",
        category="runtime_write",
        input_schema={
            "type": "object",
            "properties": {
                "loop_id": {"type": "string"},
                "actor": {"type": "string", "description": "Optional audit actor label."},
                "run_id": {"type": "string", "description": "Optional originating run id."},
            },
            "required": ["loop_id"],
        },
    ),
    ToolSchema(
        name="runtime_disable_loop",
        description="Disable a runtime loop spec after validation, backup, and audit.",
        category="runtime_write",
        input_schema={
            "type": "object",
            "properties": {
                "loop_id": {"type": "string"},
                "actor": {"type": "string", "description": "Optional audit actor label."},
                "run_id": {"type": "string", "description": "Optional originating run id."},
            },
            "required": ["loop_id"],
        },
    ),
)
