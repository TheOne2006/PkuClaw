from __future__ import annotations

import json
from typing import Any


def extract_text_content(content: str) -> str:
    if not content:
        return ""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content
    text = payload.get("text")
    return text if isinstance(text, str) else content


def extract_sender_open_id(event: Any) -> str | None:
    sender = getattr(event, "sender", None)
    sender_id = getattr(sender, "sender_id", None)
    open_id = getattr(sender_id, "open_id", None)
    return open_id if isinstance(open_id, str) and open_id else None


def feishu_conversation_id(open_id: str) -> str:
    return f"feishu:user:{open_id}"


def card_action_value(event: Any) -> dict[str, Any]:
    action = getattr(event, "action", None)
    value = getattr(action, "value", None)
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def card_action_operator_open_id(event: Any) -> str | None:
    operator = getattr(event, "operator", None)
    open_id = getattr(operator, "open_id", None)
    if not open_id:
        operator_id = getattr(operator, "operator_id", None)
        open_id = getattr(operator_id, "open_id", None)
    return open_id if isinstance(open_id, str) and open_id else None


def card_action_target(event: Any, operator_open_id: str | None) -> str | None:
    context = getattr(event, "context", None)
    open_chat_id = getattr(context, "open_chat_id", None)
    if isinstance(open_chat_id, str) and open_chat_id:
        return open_chat_id
    return operator_open_id


def receive_id_type_for_target(target_id: str | None) -> str:
    if target_id and target_id.startswith("oc_"):
        return "chat_id"
    return "open_id"


def card_action_toast(
    response_cls: Any,
    *,
    toast_type: str,
    content: str,
) -> Any:
    return response_cls({"toast": {"type": toast_type, "content": content}})


def int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
