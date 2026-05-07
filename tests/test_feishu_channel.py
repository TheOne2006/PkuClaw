from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import unittest
from pathlib import Path

from pkuclaw.code_agents.artifacts import codex_trace_events
from pkuclaw.channels.base import ChannelInboundMessage
from pkuclaw.channels.feishu.cards import (
    FeishuCardKitClient,
    FeishuCardRenderer,
    FeishuRunCardSink,
)
from pkuclaw.channels.feishu.events import (
    card_action_operator_open_id,
    card_action_target,
    card_action_value,
)
from pkuclaw.channels.feishu.handlers import FeishuEventHandlers
from pkuclaw.channels.feishu.tools import FeishuChannelOutboundBackend
from pkuclaw.core.models import AgentEvent
from pkuclaw.core.store import Store

from tests.helpers import (
    FakeCardModel,
    FakeCreateCardRequest,
    FakeCreateCardRequestBody,
    FakeCreateMessageRequest,
    FakeCreateMessageRequestBody,
    FakeFeishuApi,
    FakeLark,
    FakeObject,
    FakeUpdateCardRequest,
    FakeUpdateCardRequestBody,
    _buttons,
    _core_runtime,
    _element_tags,
    _fake_feishu_cardkit_client,
    _feishu_chat_target,
    _markdown_contents,
    _settings,
)


class ChannelContractTests(unittest.TestCase):
    def test_inbound_message_carries_target_context(self) -> None:
        envelope = ChannelInboundMessage(
            channel="feishu",
            conversation_id="feishu:user:open-1",
            sender_id="open-1",
            target=_feishu_chat_target(),
            text="你好",
            external_message_id="om_inbound",
        )

        self.assertEqual(envelope.target.target_type, "chat_id")
        self.assertEqual(envelope.channel_context()["channel"], "feishu")
        self.assertEqual(
            envelope.channel_context()["target"],
            {
                "channel": "feishu",
                "target_type": "chat_id",
                "target_id": "oc_chat",
            },
        )
        self.assertEqual(envelope.channel_context()["external_message_id"], "om_inbound")


class FeishuCardTests(unittest.TestCase):
    def test_renderer_builds_streaming_answer_card(self) -> None:
        card = FeishuCardRenderer().streaming_answer_card(
            run_id="abc123",
            answer_text="正在生成第一段回复",
            started_at=0.0,
        )

        self.assertTrue(card["config"]["wide_screen_mode"])
        self.assertTrue(card["config"]["update_multi"])
        self.assertTrue(card["config"]["streaming_mode"])
        self.assertEqual(card["schema"], "2.0")
        self.assertIn("pkuclaw-body", card["config"]["style"]["text_size"])
        self.assertIn("body", card)
        self.assertIn("markdown", _element_tags(card))
        self.assertNotIn("button", _element_tags(card))
        self.assertEqual(card["header"]["title"]["content"], "PkuClaw 正在回复")
        markdown = "\n".join(_markdown_contents(card))
        self.assertIn("正在生成第一段回复", markdown)
        self.assertNotIn("请求", markdown)
        self.assertNotIn("最近事件", markdown)
        self.assertNotIn("结果文件", markdown)

    def test_renderer_preserves_card_markdown_shape(self) -> None:
        card = FeishuCardRenderer().final_answer_card(
            status="succeeded",
            run_id="abc123",
            response_text=(
                "# 标题\n\n"
                "- 第一项\n"
                "- 第二项\n\n"
                "路径 `configs/runtime/runtime.json`\n\n"
                "```py\n"
                "print('<at id=all></at>')\n"
                "```\n"
            ),
            started_at=0.0,
            finished_at=1.0,
        )

        self.assertFalse(card["config"]["streaming_mode"])
        markdown = "\n".join(_markdown_contents(card))
        self.assertIn("# 标题", markdown)
        self.assertIn("- 第一项", markdown)
        self.assertIn("路径 configs/runtime/runtime.json", markdown)
        self.assertNotIn("路径 `configs/runtime/runtime.json`", markdown)
        self.assertIn("```python", markdown)
        self.assertIn("＜at id=all>＜/at>", markdown)
        self.assertNotIn("最近事件", markdown)
        self.assertNotIn("结果文件", markdown)
        buttons = _buttons(card)
        self.assertEqual(len(buttons), 1)
        self.assertEqual(
            buttons[0]["behaviors"][0]["value"],
            {"action": "show_run_details", "run_id": "abc123", "page": 0},
        )
        self.assertNotIn("value", buttons[0])

    def test_renderer_builds_paginated_run_detail_card(self) -> None:
        card = FeishuCardRenderer().run_detail_card(
            run_id="abc123456789",
            status="succeeded",
            elapsed="3.0s",
            agent_context={"mode": "Fast", "model": "gpt-test", "reasoning": "low"},
            artifacts={
                "prompt": "prompt.md",
                "stdout": "stdout.jsonl",
                "stderr": "stderr.log",
                "result": "result.md",
            },
            events=[f"{index}. event" for index in range(45)],
            page=1,
        )

        markdown = "\n".join(_markdown_contents(card))
        self.assertIn("Codex events · 2/2", markdown)
        self.assertIn("stdout.jsonl", markdown)
        self.assertIn("gpt-test", markdown)
        self.assertIn("button", _element_tags(card))
        buttons = _buttons(card)
        self.assertEqual(buttons[0]["behaviors"][0]["type"], "callback")
        self.assertEqual(buttons[0]["behaviors"][0]["value"]["action"], "detail_page")
        self.assertEqual(buttons[0]["behaviors"][0]["value"]["page"], 0)

    def test_cardkit_client_creates_sends_and_updates_card(self) -> None:
        fake_api = FakeFeishuApi()
        client = FeishuCardKitClient(
            lark=FakeLark(),
            client=fake_api,
            create_message_request=FakeCreateMessageRequest,
            create_message_request_body=FakeCreateMessageRequestBody,
            create_card_request=FakeCreateCardRequest,
            create_card_request_body=FakeCreateCardRequestBody,
            update_card_request=FakeUpdateCardRequest,
            update_card_request_body=FakeUpdateCardRequestBody,
            card_model=FakeCardModel,
        )

        sent_card = client.send_card(
            receive_id_type="chat_id",
            receive_id="oc_chat",
            card={"schema": "2.0", "body": {"elements": []}},
        )
        client.update_card(
            card_id=sent_card.card_id,
            card={"schema": "2.0", "body": {"elements": []}},
            sequence=1,
        )

        self.assertEqual(sent_card.message_id, "om_1")
        self.assertEqual(sent_card.card_id, "card_1")
        self.assertEqual(fake_api.cardkit.v1.card.created.body.type, "card_json")
        self.assertEqual(fake_api.cardkit.v1.card.updated.card_id, "card_1")
        self.assertEqual(fake_api.cardkit.v1.card.updated.body.sequence, 1)
        self.assertEqual(fake_api.im.v1.message.created.body.msg_type, "interactive")
        content = json.loads(fake_api.im.v1.message.created.body.content)
        self.assertEqual(content["type"], "card")
        self.assertEqual(content["data"]["card_id"], "card_1")

    def test_run_card_sink_records_and_updates_one_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            run = store.create_run(
                conversation_id="feishu:user:open-1",
                user_text="你好",
                intent="general",
            )
            fake_api = FakeFeishuApi()
            sink = FeishuRunCardSink(
                client=_fake_feishu_cardkit_client(fake_api),
                renderer=FeishuCardRenderer(),
                store=store,
                target=_feishu_chat_target(),
                run_id=run.run_id,
            )

            sink.start()
            sink.emit(
                AgentEvent(
                    run_id=run.run_id,
                    kind="output",
                    phase="output",
                    message="hello",
                )
            )
            sink.emit(
                AgentEvent(
                    run_id=run.run_id,
                    kind="final",
                    phase="finished",
                    message="hello\nworld",
                    data={"status": "succeeded", "result_path": "result.md"},
                )
            )

            record = store.get_channel_message(
                run_id=run.run_id,
                channel="feishu",
                target_id="oc_chat",
            )
            self.assertIsNotNone(record)
            self.assertEqual(record.external_message_id, "om_1")
            self.assertEqual(
                fake_api.im.v1.message.created.body.msg_type,
                "interactive",
            )
            self.assertEqual(fake_api.cardkit.v1.card.update_count, 2)
            self.assertEqual(fake_api.cardkit.v1.card.updated.body.sequence, 2)
            final_card = json.loads(fake_api.cardkit.v1.card.updated.body.card.data)
            self.assertFalse(final_card["config"]["streaming_mode"])
            self.assertIn("hello\nworld", "\n".join(_markdown_contents(final_card)))


class FeishuCardActionTests(unittest.TestCase):
    def test_card_action_helpers_extract_value_and_target(self) -> None:
        event = FakeObject(
            action=FakeObject(
                value={"action": "show_run_details", "run_id": "run-1", "page": 0}
            ),
            operator=FakeObject(open_id="ou_user"),
            context=FakeObject(open_chat_id="oc_chat"),
        )

        self.assertEqual(card_action_value(event)["run_id"], "run-1")
        self.assertEqual(card_action_operator_open_id(event), "ou_user")
        self.assertEqual(card_action_target(event, "ou_user"), "oc_chat")

    def test_codex_trace_events_summarizes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout_path = Path(tmp) / "stdout.jsonl"
            stdout_path.write_text(
                '{"type":"exec_command","command":"uv run python -m unittest"}\n'
                '{"type":"agent_message","text":"hello\\nworld"}\n',
                encoding="utf-8",
            )

            events = codex_trace_events(stdout_path)

        self.assertIn("exec_command: command uv run python", events[0])
        self.assertIn("agent_message: hello world", events[1])


class FeishuOutboxTests(unittest.TestCase):
    def test_send_text_renders_exact_control_card_payload(self) -> None:
        fake_api = FakeFeishuApi()
        renderer = FeishuCardRenderer()
        backend = FeishuChannelOutboundBackend(
            client=_fake_feishu_cardkit_client(fake_api),
            renderer=renderer,
        )

        text = "已切换 Agent 到 Fast 模式。"
        backend.send_text(target=_feishu_chat_target(), text=text)

        created_card = json.loads(fake_api.cardkit.v1.card.created.body.data)
        self.assertEqual(
            created_card,
            renderer.control_card(title="PkuClaw", body=text),
        )

    def test_local_control_menu_uses_same_control_card_rendering(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            ThreadPoolExecutor(max_workers=1) as executor,
            ThreadPoolExecutor(max_workers=1) as callback_executor,
        ):
            root = Path(tmp)
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)
            fake_api = FakeFeishuApi()
            renderer = FeishuCardRenderer()
            message_client = _fake_feishu_cardkit_client(fake_api)
            core_runtime.register_channel_backend(
                FeishuChannelOutboundBackend(
                    client=message_client,
                    renderer=renderer,
                )
            )
            handler = FeishuEventHandlers(
                settings=_settings(root),
                core_runtime=core_runtime,
                message_client=message_client,
                card_renderer=renderer,
                card_action_response_cls=lambda payload: payload,
                executor=executor,
                callback_executor=callback_executor,
            )

            handler.on_bot_menu(
                FakeObject(
                    event=FakeObject(
                        event_key="mode:fast",
                        operator=FakeObject(
                            operator_id=FakeObject(open_id="ou_user"),
                        ),
                    )
                )
            )

        self.assertEqual(fake_api.im.v1.message.created.body.receive_id, "ou_user")
        self.assertEqual(fake_api.im.v1.message.created.receive_id_type, "open_id")
        created_card = json.loads(fake_api.cardkit.v1.card.created.body.data)
        self.assertEqual(
            created_card,
            renderer.control_card(title="PkuClaw", body="已切换 Agent 到 Fast 模式。"),
        )

    def test_feishu_outbox_backend_sends_text_and_reports_image_gap(self) -> None:
        fake_api = FakeFeishuApi()
        backend = FeishuChannelOutboundBackend(
            client=_fake_feishu_cardkit_client(fake_api),
            renderer=FeishuCardRenderer(),
        )

        result = backend.send_text(target=_feishu_chat_target(), text="hello")
        image_result = backend.send_image(
            target=_feishu_chat_target(),
            image_path="image.png",
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.data["message_id"], "om_1")
        self.assertEqual(result.target, _feishu_chat_target())
        self.assertEqual(result.external_message_id, "om_1")
        self.assertFalse(image_result.ok)
        self.assertIn("not implemented", image_result.message)
