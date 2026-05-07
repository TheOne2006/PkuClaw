#!/usr/bin/env python3
"""One-shot Feishu ID capture helper for PkuClaw runtime notifications.

Run this, then DM the bot or @ it in a group. The first text message event updates
configs/runtime/runtime.json notifications target:
- p2p/DM -> open_id (ou_xxx)
- group/topic_group -> chat_id (oc_xxx)
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pkuclaw.config import load_settings  # noqa: E402
from pkuclaw.channels.feishu.events import (  # noqa: E402
    extract_sender_open_id,
    extract_text_content,
)
from pkuclaw.channels.feishu.ids import short_id  # noqa: E402
from pkuclaw.channels.feishu.sdk import load_feishu_sdk, new_ws_client  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture Feishu open_id/chat_id from the next bot message and write runtime.json."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config TOML. Defaults to PkuClaw config resolution.",
    )
    parser.add_argument(
        "--runtime",
        type=Path,
        default=ROOT / "configs" / "runtime" / "runtime.json",
        help="Path to runtime.json to update.",
    )
    parser.add_argument(
        "--target",
        choices=("auto", "user", "chat"),
        default="auto",
        help="Which target to write: auto uses open_id for DM and chat_id for groups.",
    )
    parser.add_argument(
        "--policy",
        default=None,
        help="Optional notifications.policy override. Defaults to preserving current value.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create runtime.json.bak before writing.",
    )
    parser.add_argument(
        "--exit-delay",
        type=float,
        default=0.5,
        help="Seconds to wait after capture before exiting the process.",
    )
    return parser.parse_args()


def _safe_get(obj: Any, *names: str) -> Any:
    cur = obj
    for name in names:
        if cur is None:
            return None
        cur = getattr(cur, name, None)
    return cur


def _json_dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _write_runtime(
    runtime_path: Path,
    *,
    target_type: str,
    target_id: str,
    policy: str | None,
    backup: bool,
) -> None:
    runtime_path = runtime_path.expanduser().resolve()
    data = json.loads(runtime_path.read_text(encoding="utf-8"))
    notifications = data.setdefault("notifications", {})
    if policy is not None:
        notifications["policy"] = policy
    else:
        notifications.setdefault("policy", "important_only")
    notifications["default_channel"] = "feishu"
    notifications["default_target_type"] = target_type
    notifications["default_target_id"] = target_id

    if backup:
        backup_path = runtime_path.with_suffix(runtime_path.suffix + ".bak")
        backup_path.write_text(runtime_path.read_text(encoding="utf-8"), encoding="utf-8")
    runtime_path.write_text(_json_dump(data), encoding="utf-8")


def _choose_target(
    *,
    mode: str,
    chat_type: str | None,
    open_id: str,
    chat_id: str,
) -> tuple[str, str]:
    if mode == "user":
        return "open_id", open_id
    if mode == "chat":
        return "chat_id", chat_id
    if chat_type in {"group", "topic_group"}:
        return "chat_id", chat_id
    return "open_id", open_id


def main() -> int:
    args = parse_args()
    settings = load_settings(args.config)
    if settings.feishu.event_mode != "websocket":
        raise RuntimeError(f"unsupported Feishu event mode: {settings.feishu.event_mode}")

    sdk = load_feishu_sdk()
    app_secret = settings.feishu.resolve_app_secret()
    captured = threading.Event()

    def shutdown_soon() -> None:
        time.sleep(max(0.0, args.exit_delay))
        # lark-oapi ws.Client has no public stop/close API in this installed version.
        os.kill(os.getpid(), signal.SIGTERM)

    def on_message(data: Any) -> None:
        if captured.is_set():
            return
        event = getattr(data, "event", None)
        message = getattr(event, "message", None)
        if message is None:
            return
        message_type = getattr(message, "message_type", None)
        if message_type != "text":
            print(f"[skip] received non-text message_type={message_type!r}; send a text message.", flush=True)
            return

        open_id = extract_sender_open_id(event)
        chat_id = getattr(message, "chat_id", None)
        chat_type = getattr(message, "chat_type", None)
        message_id = getattr(message, "message_id", None)
        text = extract_text_content(getattr(message, "content", ""))
        if not open_id or not chat_id:
            print("[skip] event missing sender open_id or chat_id.", flush=True)
            return

        target_type, target_id = _choose_target(
            mode=args.target,
            chat_type=chat_type,
            open_id=open_id,
            chat_id=chat_id,
        )
        _write_runtime(
            args.runtime,
            target_type=target_type,
            target_id=target_id,
            policy=args.policy,
            backup=not args.no_backup,
        )
        captured.set()
        print("\n[captured] Feishu message received.", flush=True)
        print(f"  sender open_id : {open_id}", flush=True)
        print(f"  chat_id        : {chat_id}", flush=True)
        print(f"  chat_type      : {chat_type or 'unknown'}", flush=True)
        print(f"  message_id     : {message_id or 'unknown'}", flush=True)
        print(f"  text chars     : {len(text)}", flush=True)
        print(
            f"[written] notifications.default_channel=feishu, "
            f"default_target_type={target_type}, default_target_id={target_id}",
            flush=True,
        )
        print(f"[written] runtime: {args.runtime.expanduser().resolve()}", flush=True)
        print(
            f"[safe-log] short target={target_type}:{short_id(target_id)}; exiting...",
            flush=True,
        )
        threading.Thread(target=shutdown_soon, daemon=True).start()

    def on_p2p_entered(data: Any) -> None:
        # If the user opens the bot chat but sends no text, this event may arrive first.
        # It is not enough to identify the desired runtime target robustly, so only log it.
        print("[event] bot p2p chat entered; please send a text message to capture IDs.", flush=True)

    handler = (
        sdk.lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(on_p2p_entered)
        .build()
    )
    print("[start] Connecting Feishu websocket for one-shot ID capture...", flush=True)
    print("[next] Send a text DM to the bot, or @ the bot in a group.", flush=True)
    print(f"[mode] target={args.target}; runtime={args.runtime.expanduser().resolve()}", flush=True)
    client = new_ws_client(
        sdk=sdk,
        app_id=settings.feishu.app_id,
        app_secret=app_secret,
        event_handler=handler,
        domain=settings.feishu.api_base,
    )
    client.start()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[stop] interrupted by user", flush=True)
        raise SystemExit(130)
