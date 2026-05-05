"""从飞书 SDK 事件对象中提取 PkuClaw 需要的字段。"""
from __future__ import annotations

import json
from typing import Any


def extract_text_content(content: str) -> str:
    """从飞书文本消息 content JSON 中提取纯文本。"""
    if not content:
        return ""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content
    text = payload.get("text")
    return text if isinstance(text, str) else content


def extract_sender_open_id(event: Any) -> str | None:
    """从飞书事件 sender 字段中提取用户 open_id。"""
    sender = getattr(event, "sender", None)
    sender_id = getattr(sender, "sender_id", None)
    open_id = getattr(sender_id, "open_id", None)
    return open_id if isinstance(open_id, str) and open_id else None


def feishu_conversation_id(open_id: str) -> str:
    """把飞书 open_id 映射成 PkuClaw conversation_id。"""
    return f"feishu:user:{open_id}"


def card_action_value(event: Any) -> dict[str, Any]:
    """解析飞书卡片按钮回调的 value 字段。"""
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
    """从飞书卡片回调中提取操作者 open_id。"""
    operator = getattr(event, "operator", None)
    open_id = getattr(operator, "open_id", None)
    if not open_id:
        operator_id = getattr(operator, "operator_id", None)
        open_id = getattr(operator_id, "open_id", None)
    return open_id if isinstance(open_id, str) and open_id else None


def card_action_target(event: Any, operator_open_id: str | None) -> str | None:
    """选择卡片回调应回复的 chat/open_id 目标。"""
    context = getattr(event, "context", None)
    open_chat_id = getattr(context, "open_chat_id", None)
    if isinstance(open_chat_id, str) and open_chat_id:
        return open_chat_id
    return operator_open_id


def receive_id_type_for_target(target_id: str | None) -> str:
    """根据飞书目标 ID 前缀推断 receive_id_type。"""
    if target_id and target_id.startswith("oc_"):
        return "chat_id"
    return "open_id"


def card_action_toast(
    response_cls: Any,
    *,
    toast_type: str,
    content: str,
) -> Any:
    """构造飞书卡片回调 toast 响应。"""
    return response_cls({"toast": {"type": toast_type, "content": content}})


def int_value(value: Any, *, default: int) -> int:
    """把任意值安全转换为 int，失败时返回默认值。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
