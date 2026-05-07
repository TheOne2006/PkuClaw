"""封装飞书 CardKit 发卡、建卡和更新卡片的低层 API 调用。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pkuclaw.core import logging as log


@dataclass(frozen=True)
class FeishuSentCard:
    """飞书发送交互卡后返回的 message_id/card_id。"""
    message_id: str
    card_id: str


@dataclass(frozen=True)
class FeishuSentMedia:
    """飞书发送图片或文件后返回的 message_id 和资源 key。"""
    message_id: str
    resource_key: str


class FeishuCardKitClient:
    """飞书 CardKit API 的薄封装，隐藏 SDK builder 细节。"""
    def __init__(
        self,
        *,
        lark: Any,
        client: Any,
        create_message_request: Any,
        create_message_request_body: Any,
        create_card_request: Any,
        create_card_request_body: Any,
        create_image_request: Any,
        create_image_request_body: Any,
        create_file_request: Any,
        create_file_request_body: Any,
        update_card_request: Any,
        update_card_request_body: Any,
        card_model: Any,
    ) -> None:
        self.lark = lark
        self.client = client
        self.create_message_request = create_message_request
        self.create_message_request_body = create_message_request_body
        self.create_card_request = create_card_request
        self.create_card_request_body = create_card_request_body
        self.create_image_request = create_image_request
        self.create_image_request_body = create_image_request_body
        self.create_file_request = create_file_request
        self.create_file_request_body = create_file_request_body
        self.update_card_request = update_card_request
        self.update_card_request_body = update_card_request_body
        self.card_model = card_model

    def send_card(
        self,
        *,
        receive_id_type: str,
        receive_id: str,
        card: dict[str, Any],
    ) -> FeishuSentCard:
        """发送结构化卡片。"""
        card_id = self.create_card(card)
        request = (
            self.create_message_request.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                self.create_message_request_body.builder()
                .receive_id(receive_id)
                .msg_type("interactive")
                .content(_card_message_content(card_id))
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.create(request)
        self._raise_if_failed(response, "client.im.v1.message.create")
        message_id = _response_message_id(response)
        if not message_id:
            raise RuntimeError("Feishu create message response missing message_id")
        return FeishuSentCard(message_id=message_id, card_id=card_id)

    def send_image(
        self,
        *,
        receive_id_type: str,
        receive_id: str,
        image_path: str,
    ) -> FeishuSentMedia:
        """上传图片并发送图片消息。"""
        image_key = self.upload_image(image_path)
        message_id = self.send_message(
            receive_id_type=receive_id_type,
            receive_id=receive_id,
            msg_type="image",
            content={"image_key": image_key},
        )
        return FeishuSentMedia(message_id=message_id, resource_key=image_key)

    def send_file(
        self,
        *,
        receive_id_type: str,
        receive_id: str,
        file_path: str,
        file_name: str | None = None,
        file_type: str | None = None,
    ) -> FeishuSentMedia:
        """上传文件并发送文件消息。"""
        file_key = self.upload_file(
            file_path=file_path,
            file_name=file_name,
            file_type=file_type,
        )
        message_id = self.send_message(
            receive_id_type=receive_id_type,
            receive_id=receive_id,
            msg_type="file",
            content={"file_key": file_key},
        )
        return FeishuSentMedia(message_id=message_id, resource_key=file_key)

    def create_card(self, card: dict[str, Any]) -> str:
        """在飞书 CardKit 中创建卡片并返回 card_id。"""
        request = (
            self.create_card_request.builder()
            .request_body(
                self.create_card_request_body.builder()
                .type("card_json")
                .data(_card_data(card))
                .build()
            )
            .build()
        )
        response = self.client.cardkit.v1.card.create(request)
        self._raise_if_failed(response, "client.cardkit.v1.card.create")
        card_id = _response_card_id(response)
        if not card_id:
            raise RuntimeError("Feishu create card response missing card_id")
        return card_id

    def upload_image(self, image_path: str) -> str:
        """上传消息图片并返回 image_key。"""
        path = Path(image_path).expanduser()
        with path.open("rb") as image:
            request = (
                self.create_image_request.builder()
                .request_body(
                    self.create_image_request_body.builder()
                    .image_type("message")
                    .image(image)
                    .build()
                )
                .build()
            )
            response = self.client.im.v1.image.create(request)
        self._raise_if_failed(response, "client.im.v1.image.create")
        image_key = _response_image_key(response)
        if not image_key:
            raise RuntimeError("Feishu create image response missing image_key")
        return image_key

    def upload_file(
        self,
        *,
        file_path: str,
        file_name: str | None = None,
        file_type: str | None = None,
    ) -> str:
        """上传消息文件并返回 file_key。"""
        path = Path(file_path).expanduser()
        with path.open("rb") as file:
            request = (
                self.create_file_request.builder()
                .request_body(
                    self.create_file_request_body.builder()
                    .file_type(file_type or _file_type_for(path))
                    .file_name(file_name or path.name)
                    .file(file)
                    .build()
                )
                .build()
            )
            response = self.client.im.v1.file.create(request)
        self._raise_if_failed(response, "client.im.v1.file.create")
        file_key = _response_file_key(response)
        if not file_key:
            raise RuntimeError("Feishu create file response missing file_key")
        return file_key

    def send_message(
        self,
        *,
        receive_id_type: str,
        receive_id: str,
        msg_type: str,
        content: dict[str, Any],
    ) -> str:
        """发送一个普通飞书 IM 消息并返回 message_id。"""
        request = (
            self.create_message_request.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                self.create_message_request_body.builder()
                .receive_id(receive_id)
                .msg_type(msg_type)
                .content(_message_content(content))
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.create(request)
        self._raise_if_failed(response, "client.im.v1.message.create")
        message_id = _response_message_id(response)
        if not message_id:
            raise RuntimeError("Feishu create message response missing message_id")
        return message_id

    def update_card(
        self,
        *,
        card_id: str,
        card: dict[str, Any],
        sequence: int,
    ) -> None:
        """更新已发送的卡片。"""
        card_payload = (
            self.card_model.builder()
            .type("card_json")
            .data(_card_data(card))
            .build()
        )
        request = (
            self.update_card_request.builder()
            .card_id(card_id)
            .request_body(
                self.update_card_request_body.builder()
                .card(card_payload)
                .uuid(f"pkuclaw_{card_id}_{sequence}")
                .sequence(sequence)
                .build()
            )
            .build()
        )
        response = self.client.cardkit.v1.card.update(request)
        self._raise_if_failed(response, "client.cardkit.v1.card.update")

    def _raise_if_failed(self, response: Any, operation: str) -> None:
        """检查飞书 SDK 响应，失败时抛出带 log_id 的错误。"""
        if response.success():
            return
        log_id = response.get_log_id()
        raise RuntimeError(
            f"{operation} failed, code={response.code}, msg={response.msg}, "
            f"log_id={log_id}, resp={_format_raw_response(self.lark, response)}"
        )


def _card_data(card: dict[str, Any]) -> str:
    """把卡片 JSON 压缩序列化为飞书 SDK 需要的字符串。"""
    return json.dumps(card, ensure_ascii=False, separators=(",", ":"))


def _card_message_content(card_id: str) -> str:
    """把 card_id 包装成飞书 interactive message content。"""
    return json.dumps(
        {
            "type": "card",
            "data": {
                "card_id": card_id,
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _message_content(content: dict[str, Any]) -> str:
    """把普通消息 content 压缩序列化。"""
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"))


def _response_message_id(response: Any) -> str | None:
    """从飞书响应对象中安全提取 message_id。"""
    data = getattr(response, "data", None)
    message_id = getattr(data, "message_id", None)
    return message_id if isinstance(message_id, str) and message_id else None


def _response_card_id(response: Any) -> str | None:
    """从飞书响应对象中安全提取 card_id。"""
    data = getattr(response, "data", None)
    card_id = getattr(data, "card_id", None)
    return card_id if isinstance(card_id, str) and card_id else None


def _response_image_key(response: Any) -> str | None:
    """从飞书响应对象中安全提取 image_key。"""
    data = getattr(response, "data", None)
    image_key = getattr(data, "image_key", None)
    return image_key if isinstance(image_key, str) and image_key else None


def _response_file_key(response: Any) -> str | None:
    """从飞书响应对象中安全提取 file_key。"""
    data = getattr(response, "data", None)
    file_key = getattr(data, "file_key", None)
    return file_key if isinstance(file_key, str) and file_key else None


def _file_type_for(path: Path) -> str:
    """Map common extensions to Feishu file_type values."""
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "pdf":
        return "pdf"
    if suffix in {"doc", "docx"}:
        return "doc"
    if suffix in {"xls", "xlsx", "csv"}:
        return "xls"
    if suffix in {"ppt", "pptx"}:
        return "ppt"
    if suffix in {"mp4", "mov", "m4v"}:
        return "mp4"
    return "stream"


def _format_raw_response(lark: Any, response: Any) -> str:
    """尽量把飞书原始响应格式化成人类可读文本。"""
    raw = getattr(response, "raw", None)
    content = getattr(raw, "content", None)
    if not content:
        return ""
    try:
        return json.dumps(json.loads(content), ensure_ascii=False)
    except (TypeError, json.JSONDecodeError, UnicodeDecodeError):
        if isinstance(content, bytes):
            return str(content, lark.UTF_8, errors="replace")
        return str(content)
