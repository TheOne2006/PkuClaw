"""MCP schema registry for loop channel notification tools."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


JsonSchema = dict[str, Any]


@dataclass(frozen=True)
class ToolSchema:
    """MCP tool name, description, input schema and category."""

    name: str
    description: str
    input_schema: JsonSchema
    category: str = "channel"

    def as_mcp_tool(self) -> dict[str, Any]:
        """Convert to the MCP tools/list JSON shape."""

        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def list_tool_schemas() -> list[dict[str, Any]]:
    """Return JSON-serializable MCP tool schema objects."""

    return [tool.as_mcp_tool() for tool in TOOL_REGISTRY]


def render_tool_prompt() -> str:
    """Render concise loop-facing channel notification tool docs."""

    lines = [
        "Use these channel notification tools only when a loop finds an important change.",
        "Normal loop completion should stay silent.",
        "",
        "### Channel notification tools",
    ]
    for tool in TOOL_REGISTRY:
        required = _required_args(tool.input_schema)
        required_text = f"; required: {', '.join(required)}" if required else ""
        lines.append(f"- `{tool.name}`{required_text}: {tool.description}")
    return "\n".join(lines).strip()


def _required_args(schema: Mapping[str, Any]) -> tuple[str, ...]:
    """Extract required argument names from a JSON schema."""

    value = schema.get("required", ())
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


TOOL_REGISTRY: tuple[ToolSchema, ...] = (
    ToolSchema(
        name="channel_send_text",
        description="Send a concise text notification through the configured channel outbox.",
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
        description="Send a structured card notification through the configured channel outbox.",
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
        description="Send an image notification through the configured channel outbox.",
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
        description="Update a previously sent card notification.",
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
)
