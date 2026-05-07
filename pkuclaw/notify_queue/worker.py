"""Daemon-side file queue worker for channel outbox messages."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time
from typing import Any

from pkuclaw.channels.base import ChannelOutboundResult
from pkuclaw.core import logging as log
from pkuclaw.core.runtime import CoreRuntime


OUTBOX_SCHEMA_VERSION = 2
NotifyResponse = dict[str, Any]


@dataclass
class NotifyQueueWorker:
    """Poll pending outbox jobs and delegate delivery to CoreRuntime."""

    queue_dir: Path
    scan_interval_seconds: int
    core_runtime: CoreRuntime
    default_channel: str = "feishu"

    def serve_forever(self) -> None:
        """Continuously scan the queue directory for pending jobs."""

        _ensure_dirs(self.queue_dir)
        log.ok(
            "Outbox queue scanning: "
            f"{self.pending_dir} every {self.scan_interval_seconds}s"
        )
        while True:
            try:
                self.process_pending()
            except Exception as exc:  # pragma: no cover - defensive daemon loop
                log.warn(f"outbox queue scan failed: {exc}")
            time.sleep(self.scan_interval_seconds)

    @property
    def pending_dir(self) -> Path:
        return self.queue_dir / "pending"

    @property
    def processing_dir(self) -> Path:
        return self.queue_dir / "processing"

    @property
    def done_dir(self) -> Path:
        return self.queue_dir / "done"

    @property
    def failed_dir(self) -> Path:
        return self.queue_dir / "failed"

    @property
    def ack_dir(self) -> Path:
        return self.queue_dir / "acks"

    def process_pending(self) -> int:
        """Process all pending JSON jobs once; return processed count."""

        _ensure_dirs(self.queue_dir)
        count = 0
        for pending_path in sorted(self.pending_dir.glob("*.json")):
            if self._process_one(pending_path):
                count += 1
        return count

    def _process_one(self, pending_path: Path) -> bool:
        processing_path = self.processing_dir / pending_path.name
        try:
            pending_path.replace(processing_path)
        except FileNotFoundError:
            return False

        job_id = processing_path.stem
        response: NotifyResponse
        ok = False
        try:
            job = _read_job(processing_path)
            job_id = _optional_str(job, "job_id") or job_id
            response = self.handle_job(job)
            ok = bool(response.get("ok"))
        except Exception as exc:
            response = _error_response(str(exc))
        response.setdefault("data", {})
        response["data"].setdefault("job_id", job_id)
        response["data"].setdefault("processed_at", _utc_now())
        _write_json_atomic(self.ack_dir / f"{job_id}.json", response)
        destination = self.done_dir if ok else self.failed_dir
        shutil.move(str(processing_path), str(destination / processing_path.name))
        return True

    def handle_job(self, job: dict[str, Any]) -> NotifyResponse:
        """Validate and execute one outbox queue job."""

        schema_version = job.get("schema_version")
        if schema_version != OUTBOX_SCHEMA_VERSION:
            raise RuntimeError("unsupported outbox job schema_version")
        kind = _required_str(job, "kind")
        payload = _required_object(job, "payload")
        if kind == "text":
            return self._send_text(job, payload)
        if kind == "image":
            return self._send_image(job, payload)
        if kind == "file":
            return self._send_file(job, payload)
        raise RuntimeError(f"unsupported outbox job kind: {kind}")

    def _send_text(self, job: dict[str, Any], payload: dict[str, Any]) -> NotifyResponse:
        text = _required_str(payload, "text")
        title = _optional_str(payload, "title")
        target = self._outbox_target(job)
        result = self.core_runtime.send_channel_text(
            channel=target["channel"],
            target_type=target["target_type"],
            target_id=target["target_id"],
            text=text,
            title=title,
        )
        return _as_response(result)

    def _send_image(self, job: dict[str, Any], payload: dict[str, Any]) -> NotifyResponse:
        path = _required_str(payload, "path")
        caption = _optional_str(payload, "caption")
        target = self._outbox_target(job)
        result = self.core_runtime.send_channel_image(
            channel=target["channel"],
            target_type=target["target_type"],
            target_id=target["target_id"],
            image_path=path,
            caption=caption,
        )
        return _as_response(result)

    def _send_file(self, job: dict[str, Any], payload: dict[str, Any]) -> NotifyResponse:
        path = _required_str(payload, "path")
        caption = _optional_str(payload, "caption")
        target = self._outbox_target(job)
        result = self.core_runtime.send_channel_file(
            channel=target["channel"],
            target_type=target["target_type"],
            target_id=target["target_id"],
            file_path=path,
            caption=caption,
        )
        return _as_response(result)

    def _outbox_target(self, job: dict[str, Any]) -> dict[str, str]:
        run_id = _optional_str(job, "run_id")
        loop_id = _optional_str(job, "loop_id")
        target = self.core_runtime.resolve_outbox_target(
            run_id=run_id,
            loop_id=loop_id,
        )
        if target is None:
            raise RuntimeError(
                "no outbox target configured; provide a run_id with channel target, "
                "a loop_id with target override, or notifications.default_channel/"
                "default_target_type/default_target_id"
            )
        return target


def _ensure_dirs(queue_dir: Path) -> None:
    for name in ("pending", "processing", "done", "failed", "acks"):
        (queue_dir / name).mkdir(parents=True, exist_ok=True)


def _read_job(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("outbox job must be a JSON object")
    return data


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _as_response(result: ChannelOutboundResult) -> NotifyResponse:
    data = dict(result.data)
    if result.external_message_id is not None:
        data.setdefault("message_id", result.external_message_id)
    if result.external_card_id is not None:
        data.setdefault("card_id", result.external_card_id)
    return {
        "ok": result.ok,
        "message": result.message,
        "data": data,
        "target": result.target.as_context() if result.target is not None else None,
    }


def _error_response(message: str) -> NotifyResponse:
    return {"ok": False, "message": message, "data": {}, "target": None}


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{key} is required")
    return value.strip()


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _required_object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"{key} must be an object")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
