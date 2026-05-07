#!/usr/bin/env python3
"""Enqueue one PkuClaw outbox job for the local daemon to deliver."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import uuid
from typing import Any


DEFAULT_QUEUE_DIR = "data/notify_queue"
OUTBOX_SCHEMA_VERSION = 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--queue-dir",
        default=(
            os.environ.get("PKUCLAW_OUTBOX_QUEUE_DIR")
            or DEFAULT_QUEUE_DIR
        ),
        help="Outbox queue directory shared with the PkuClaw daemon.",
    )
    parser.add_argument(
        "--run-id",
        default=os.environ.get("PKUCLAW_RUN_ID", "").strip() or None,
        help="Current PkuClaw run id used by the daemon to resolve the channel target.",
    )
    parser.add_argument(
        "--run-source",
        default=os.environ.get("PKUCLAW_RUN_SOURCE", "").strip() or None,
        help="Current PkuClaw run source, usually realtime or loop.",
    )
    parser.add_argument(
        "--loop-id",
        default=os.environ.get("PKUCLAW_LOOP_ID", "").strip() or None,
        help="Optional loop id used as target fallback for loop runs.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=30.0,
        help="Seconds to wait for daemon ack after enqueueing.",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Return after writing the queue file without waiting for daemon ack.",
    )
    subparsers = parser.add_subparsers(dest="kind", required=True)

    text = subparsers.add_parser("text", help="Enqueue a text outbox message.")
    text.add_argument("--text", required=True, help="Markdown-capable text body.")
    text.add_argument("--title", default=None, help="Optional human-facing title.")

    image = subparsers.add_parser("image", help="Enqueue an image outbox message.")
    image.add_argument("--path", required=True, type=Path, help="Image path to send.")
    image.add_argument("--caption", default=None, help="Optional image caption.")

    file = subparsers.add_parser("file", help="Enqueue a file outbox message.")
    file.add_argument("--path", required=True, type=Path, help="File path to send.")
    file.add_argument("--caption", default=None, help="Optional file caption.")

    args = parser.parse_args()
    queue_dir = Path(args.queue_dir).expanduser()
    job = _build_job(args)
    pending_path = _enqueue(queue_dir=queue_dir, job=job)

    if args.no_wait:
        _print_json(
            {
                "ok": True,
                "message": "queued",
                "data": {
                    "job_id": job["job_id"],
                    "job_path": str(pending_path),
                    "ack_path": str(_ack_path(queue_dir, job["job_id"])),
                },
                "target": None,
            }
        )
        return 0

    response = _wait_for_ack(
        queue_dir=queue_dir,
        job_id=job["job_id"],
        wait_seconds=max(0.0, args.wait_seconds),
    )
    _print_json(response)
    return 0 if response.get("ok") is True else 1


def _build_job(args: argparse.Namespace) -> dict[str, Any]:
    if args.kind == "text":
        payload = {"text": args.text}
        if _optional_text(args.title):
            payload["title"] = _optional_text(args.title)
    elif args.kind == "image":
        payload = {"path": str(args.path.expanduser())}
        if _optional_text(args.caption):
            payload["caption"] = _optional_text(args.caption)
    elif args.kind == "file":
        payload = {"path": str(args.path.expanduser())}
        if _optional_text(args.caption):
            payload["caption"] = _optional_text(args.caption)
    else:  # pragma: no cover - argparse enforces known subcommands
        raise SystemExit(f"unsupported outbox kind: {args.kind}")

    job: dict[str, Any] = {
        "schema_version": OUTBOX_SCHEMA_VERSION,
        "job_id": uuid.uuid4().hex,
        "kind": args.kind,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    if args.run_id:
        job["run_id"] = args.run_id
    if args.run_source:
        job["run_source"] = args.run_source
    if args.loop_id:
        job["loop_id"] = args.loop_id
    return job


def _enqueue(*, queue_dir: Path, job: dict[str, Any]) -> Path:
    pending_dir = queue_dir / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    job_id = str(job["job_id"])
    final_path = pending_dir / f"{job_id}.json"
    tmp_path = pending_dir / f".{job_id}.json.tmp"
    tmp_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(final_path)
    return final_path


def _wait_for_ack(*, queue_dir: Path, job_id: str, wait_seconds: float) -> dict[str, Any]:
    ack_path = _ack_path(queue_dir, job_id)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() <= deadline:
        if ack_path.exists():
            return _read_json_object(ack_path)
        time.sleep(0.2)
    return {
        "ok": False,
        "message": "outbox queued but daemon ack timed out",
        "data": {"job_id": job_id, "ack_path": str(ack_path)},
        "target": None,
    }


def _ack_path(queue_dir: Path, job_id: str) -> Path:
    return queue_dir / "acks" / f"{job_id}.json"


def _read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"JSON file must contain an object: {path}")
    return data


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _print_json(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
