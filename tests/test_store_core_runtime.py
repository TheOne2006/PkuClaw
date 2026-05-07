from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pkuclaw.channels.base import ChannelInboundMessage
from pkuclaw.core.store import Store

from tests.helpers import _core_runtime, _feishu_chat_target


class StoreAndCoreRuntimeTests(unittest.TestCase):
    def test_conversation_mode_and_local_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            loop = _core_runtime(Path(tmp), store)

            dispatch = loop.ingest_channel_message(
                ChannelInboundMessage(
                    channel="feishu",
                    conversation_id="feishu:user:open-1",
                    sender_id="open-1",
                    target=_feishu_chat_target(),
                    text="",
                    event_key="mode:fast",
                )
            )

            self.assertTrue(dispatch.handled_locally)
            self.assertIsNone(dispatch.run_id)
            self.assertIn("Fast", dispatch.reply_text)
            conversation = store.ensure_conversation("feishu:user:open-1")
            self.assertEqual(conversation.agent_settings.mode, "fast")

            dispatch = loop.ingest_channel_message(
                ChannelInboundMessage(
                    channel="feishu",
                    conversation_id="feishu:user:open-1",
                    sender_id="open-1",
                    target=_feishu_chat_target(),
                    text="",
                    event_key="reasoning:high",
                )
            )

            self.assertTrue(dispatch.handled_locally)
            conversation = store.ensure_conversation("feishu:user:open-1")
            self.assertEqual(conversation.agent_settings.reasoning_effort, "high")

    def test_user_message_creates_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            loop = _core_runtime(Path(tmp), store)

            dispatch = loop.ingest_channel_message(
                ChannelInboundMessage(
                    channel="feishu",
                    conversation_id="feishu:user:open-1",
                    sender_id="open-1",
                    target=_feishu_chat_target(),
                    text="你好",
                )
            )

            self.assertFalse(dispatch.handled_locally)
            self.assertIsNotNone(dispatch.run_id)
            self.assertIsNotNone(dispatch.agent_request)
            self.assertEqual(dispatch.channel_target, _feishu_chat_target())
            self.assertEqual(
                dispatch.agent_request.channel_context["target"]["target_id"],
                "oc_chat",
            )
            self.assertEqual(store.counts_by_status(), {"queued": 1})

    def test_unknown_event_key_does_not_create_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            loop = _core_runtime(Path(tmp), store)

            dispatch = loop.ingest_channel_message(
                ChannelInboundMessage(
                    channel="feishu",
                    conversation_id="feishu:user:open-1",
                    sender_id="open-1",
                    target=_feishu_chat_target(),
                    text="",
                    event_key="unknown:action",
                )
            )

            self.assertTrue(dispatch.handled_locally)
            self.assertIsNone(dispatch.run_id)
            self.assertEqual(store.counts_by_status(), {})

    def test_records_channel_message_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            run = store.create_run(
                conversation_id="feishu:user:open-1",
                user_text="你好",
                intent="chat",
            )

            store.record_channel_message(
                run_id=run.run_id,
                channel="feishu",
                target_id="oc_chat",
                external_message_id="om_message",
            )

            record = store.get_channel_message(
                run_id=run.run_id,
                channel="feishu",
                target_id="oc_chat",
            )
            self.assertIsNotNone(record)
            self.assertEqual(record.external_message_id, "om_message")
