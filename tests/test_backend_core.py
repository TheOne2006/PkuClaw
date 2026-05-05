from __future__ import annotations

import ast
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pkuclaw.agents import AgentWrapper
from pkuclaw.code_agents.artifacts import codex_trace_events
from pkuclaw.code_agents.subskills import (
    load_skill_registry,
    render_subskills,
    resolve_subskill_names,
)
from pkuclaw.channels.base import (
    ChannelInboundMessage,
    ChannelOutboundResult,
    ChannelTarget,
)
from pkuclaw.channels.feishu.cards import (
    FeishuCardKitClient,
    FeishuCardRenderer,
    FeishuRunCardSink,
)
from pkuclaw.channels.feishu.tools import FeishuChannelOutboundBackend
from pkuclaw.channels.feishu.events import (
    card_action_operator_open_id,
    card_action_target,
    card_action_value,
)
from pkuclaw.config import (
    AgentConfig,
    AppConfig,
    CodexConfig,
    FeishuConfig,
    McpConfig,
    MonitorConfig,
    Settings,
)
from pkuclaw.core import logging as log
from pkuclaw.core.app import CoreRuntime
from pkuclaw.core.models import AgentEvent, AgentResult
from pkuclaw.core.router import classify_message
from pkuclaw.core.store import Store
from pkuclaw.loop import LoopManager
from pkuclaw.mcp.handlers import DaemonMcpToolHandler
from pkuclaw.mcp.server import handle_mcp_request
from pkuclaw.runtime_config import RuntimeConfigStore
from pkuclaw.runtime import (
    build_core_runtime_services,
    build_runtime_bootstrap,
)


class RouterTests(unittest.TestCase):
    def test_classifies_notes(self) -> None:
        plan = classify_message("帮我继续多智能体基础的笔记")
        self.assertEqual(plan.intent, "notes")
        self.assertIn("tasks/write-notes.md", plan.skill_names)

    def test_classifies_homework(self) -> None:
        plan = classify_message("量子力学 hw5 先规划一下，不要提交")
        self.assertEqual(plan.intent, "homework")
        self.assertIn("tasks/do-homework.md", plan.skill_names)

    def test_classifies_sync(self) -> None:
        plan = classify_message("看看这周有什么要交")
        self.assertEqual(plan.intent, "sync")
        self.assertIn("tasks/sync-notices.md", plan.skill_names)


class SubSkillTests(unittest.TestCase):
    def test_resolves_subskill_dependencies(self) -> None:
        names = resolve_subskill_names(("tasks/sync-notices.md",))

        self.assertEqual(names[0], "runtime/codex-subagent.md")
        self.assertIn("tasks/sync-notices.md", names)
        self.assertIn("tools/pku3b-setup.md", names)
        self.assertIn("tools/data-parser.md", names)

    def test_runtime_registry_resolves_sync_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_dir = root / "sub-skills"
            runtime_dir = root / "configs" / "runtime"
            _write_test_subskills(skills_dir)
            _write_skills_json(runtime_dir)

            registry = load_skill_registry(
                runtime_dir / "skills.json",
                skills_dir=skills_dir,
            )
            names = resolve_subskill_names(
                ("tasks/sync-notices.md",),
                registry=registry,
                skills_dir=skills_dir,
                source="loop",
            )

        self.assertEqual(
            names,
            (
                "runtime/codex-subagent.md",
                "tasks/sync-notices.md",
                "tools/pku3b-setup.md",
                "tools/data-parser.md",
            ),
        )
        self.assertFalse(registry.using_default)

    def test_missing_skills_json_falls_back_to_default_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "sub-skills"
            _write_test_subskills(skills_dir)

            registry = load_skill_registry(
                Path(tmp) / "missing-skills.json",
                skills_dir=skills_dir,
            )
            names = resolve_subskill_names(
                ("tasks/sync-notices.md",),
                registry=registry,
                skills_dir=skills_dir,
                source="loop",
            )

        self.assertTrue(registry.using_default)
        self.assertTrue(registry.warnings)
        self.assertIn("fallback", registry.warnings[0])
        self.assertIn("tools/pku3b-setup.md", names)
        self.assertIn("tools/data-parser.md", names)

    def test_invalid_skills_json_falls_back_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_dir = root / "sub-skills"
            registry_path = root / "skills.json"
            _write_test_subskills(skills_dir)
            registry_path.write_text("{not json", encoding="utf-8")

            registry = load_skill_registry(registry_path, skills_dir=skills_dir)

        self.assertTrue(registry.using_default)
        self.assertTrue(registry.warnings)
        self.assertIn("skill registry fallback", registry.warnings[0])

    def test_escaping_skill_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_dir = root / "sub-skills"
            registry_path = root / "skills.json"
            _write_test_subskills(skills_dir)
            registry_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "skills": [
                            {
                                "name": "../escape.md",
                                "intent": "sync",
                                "dependencies": [],
                                "allowed_sources": ["realtime"],
                                "requires_confirmation": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            registry = load_skill_registry(registry_path, skills_dir=skills_dir)
            with self.assertRaisesRegex(RuntimeError, "escapes skill root"):
                resolve_subskill_names(("../escape.md",), skills_dir=skills_dir)

        self.assertTrue(registry.using_default)
        self.assertIn("escapes skill root", registry.warnings[0])

    def test_renders_subskills_from_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sub-skills"
            _write_test_subskills(root)

            rendered = render_subskills(
                ("tasks/do-homework.md",),
                skills_dir=root,
            )

            self.assertIn("## runtime/codex-subagent.md", rendered)
            self.assertIn("## tasks/do-homework.md", rendered)
            self.assertIn("## tools/pdf-reader.md", rendered)
            self.assertIn("## tools/pku3b-setup.md", rendered)


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


class AgentWrapperAndCodexTests(unittest.TestCase):
    def test_wrapper_uses_runtime_skill_registry_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_dir = root / "runtime"
            _write_runtime_json(runtime_dir)
            _write_skills_json(
                runtime_dir,
                skills=[
                    {
                        "name": "tasks/sync-notices.md",
                        "intent": "sync",
                        "dependencies": ["tools/data-parser.md"],
                        "allowed_sources": ["realtime", "loop"],
                        "requires_confirmation": False,
                    },
                    {
                        "name": "tools/data-parser.md",
                        "intent": "tool",
                        "dependencies": [],
                        "allowed_sources": ["realtime", "loop"],
                        "requires_confirmation": False,
                    },
                ],
            )
            _write_test_subskills(root / "sub-skills")
            settings = _settings(root)
            store = Store(settings.app.data_dir / "pkuclaw.db")
            wrapper = AgentWrapper(
                settings=settings,
                store=store,
                runtime_config=RuntimeConfigStore(runtime_dir),
                repo_root=root,
            )
            plan = classify_message("同步一下课程通知")
            request = _agent_request(
                conversation_id="feishu:user:open-1",
                text="同步一下课程通知",
                intent=plan.intent,
                skill_names=plan.skill_names,
            )
            prepared = wrapper.prepare(request, plan)

            context = wrapper._build_context(  # noqa: SLF001 - verify run compiler input
                run=store.get_run(prepared.run_id),
                request=prepared.request,
                plan=prepared.plan,
            )

        self.assertIn("## runtime/codex-subagent.md", context.rendered_skills)
        self.assertIn("## tasks/sync-notices.md", context.rendered_skills)
        self.assertIn("## tools/data-parser.md", context.rendered_skills)
        self.assertNotIn("## tools/pku3b-setup.md", context.rendered_skills)
        self.assertEqual(context.warnings, ())

    def test_wrapper_builds_prompt_and_codex_persists_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_dir = root / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "runtime.json").write_text(
                json.dumps(
                    {
                        "agent": {"mode": "fast", "model": "gpt-test"},
                        "codex": {"sandbox": "read-only", "timeout_seconds": 60},
                        "prompt": {
                            "fragment_paths": ["prompt-fragment.md"],
                            "default_skill_names": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "prompt-fragment.md").write_text("# Extra fragment\n", encoding="utf-8")
            _write_test_subskills(root / "sub-skills")
            settings = _settings(root)
            store = Store(settings.app.data_dir / "pkuclaw.db")
            plan = classify_message("你好")
            wrapper = AgentWrapper(
                settings=settings,
                store=store,
                runtime_config=RuntimeConfigStore(runtime_dir),
                repo_root=root,
            )
            request = _agent_request(
                conversation_id="feishu:user:open-1",
                text="你好",
                intent=plan.intent,
                skill_names=plan.skill_names,
            )
            prepared = wrapper.prepare(request, plan)

            def fake_popen(command, **kwargs):
                output_path = Path(command[command.index("-o") + 1])
                output_path.write_text(
                    "## 回复用户\n\n- hello\n- world\n",
                    encoding="utf-8",
                )
                self.assertIn("-c", command)
                self.assertIn('model_reasoning_effort="low"', command)
                self.assertIn("-m", command)
                self.assertIn("gpt-test", command)
                self.assertIn("read-only", command)
                self.assertIn(
                    'mcp_servers.pkuclaw_daemon.url="http://127.0.0.1:8765/mcp"',
                    command,
                )
                return FakePopen(
                    stdout=(
                        '{"thread_id":"thread-abc","text":"hello"}\n'
                        '{"type":"item.completed","item":{"type":"agent_message",'
                        '"text":"## partial\\n\\n- streamed"}}\n'
                        '{"type":"agent_message_delta","delta":"# streamed\\n\\n"}\n'
                    ),
                    returncode=0,
                )

            sink = CapturingSink()
            with (
                patch("pkuclaw.code_agents.codex.subprocess.Popen", side_effect=fake_popen),
                patch.object(log.console, "print"),
            ):
                result = wrapper.run(
                    run_id=prepared.run_id,
                    request=prepared.request,
                    plan=prepared.plan,
                    sink=sink,
                )

            self.assertEqual(result.status, "succeeded")
            self.assertEqual(result.session_id, "thread-abc")
            self.assertTrue(result.result_path.exists())
            self.assertTrue((settings.app.data_dir / "agent_runs").exists())
            prompt = (settings.app.data_dir / "agent_runs" / "codex" / prepared.run_id / "prompt.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("# PkuClaw Agent Run", prompt)
            self.assertIn("AgentWrapper owns prompt construction", prompt)
            self.assertIn("# Extra fragment", prompt)
            self.assertIn("## runtime/codex-subagent.md", prompt)
            self.assertIn("started", [event.kind for event in sink.events])
            self.assertIn("final", [event.kind for event in sink.events])
            output_events = [event for event in sink.events if event.kind == "output"]
            self.assertIn("\n- streamed", output_events[0].message)
            self.assertEqual(output_events[-1].message, "# streamed\n\n")
            final_event = [event for event in sink.events if event.kind == "final"][-1]
            self.assertIn("\n- hello", final_event.message)
            conversation = store.ensure_conversation("feishu:user:open-1")
            self.assertEqual(conversation.agent_session_id, "thread-abc")
            metadata = store.get_run_metadata(prepared.run_id)
            self.assertEqual(metadata["provider"], "codex")


class RuntimeConfigTests(unittest.TestCase):
    def test_runtime_json_fallback_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            loader = RuntimeConfigStore(runtime_dir)

            config = loader.read_snapshot()

            self.assertEqual(config.agent.provider, "codex")
            self.assertEqual(config.loops[0].id, "sync_notices")
            self.assertTrue(config.warnings)
            self.assertIn("fallback", config.warnings[0])

    def test_invalid_runtime_file_falls_back_to_last_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            _write_runtime_json(
                runtime_dir,
                loops=[
                    {
                        "id": "valid_loop",
                        "enabled": True,
                        "interval_seconds": 60,
                        "prompt": "valid prompt",
                        "skill_names": ["tasks/sync-notices.md"],
                        "sink_mode": "silent",
                    }
                ],
            )
            runtime_store = RuntimeConfigStore(runtime_dir)
            self.assertEqual(runtime_store.read_snapshot().loops[0].id, "valid_loop")

            (runtime_dir / "runtime.json").write_text("{not json", encoding="utf-8")

            fallback = runtime_store.read_snapshot()

            self.assertEqual(fallback.loops[0].id, "valid_loop")
            self.assertTrue(fallback.warnings)
            self.assertIn("fallback", fallback.warnings[-1])

    def test_runtime_loop_accepts_default_target_and_overlap_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            _write_runtime_json(
                runtime_dir,
                loops=[
                    {
                        "id": "targeted_loop",
                        "enabled": True,
                        "interval_seconds": 60,
                        "prompt": "targeted prompt",
                        "skill_names": [],
                        "sink_mode": "silent",
                        "notify_policy": "important_only",
                        "default_channel": "feishu",
                        "default_target_type": "chat_id",
                        "default_target_id": "oc_target",
                        "prevent_overlap": True,
                    }
                ],
            )

            loop = RuntimeConfigStore(runtime_dir).read_snapshot().loops[0]

            self.assertEqual(loop.default_channel, "feishu")
            self.assertEqual(loop.default_target_type, "chat_id")
            self.assertEqual(loop.default_target_id, "oc_target")
            self.assertTrue(loop.prevent_overlap)

    def test_add_loop_writes_runtime_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_json(root / "runtime")
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)

            result = core_runtime.add_loop(
                loop={
                    "id": "weekly_review",
                    "enabled": True,
                    "interval_seconds": 3600,
                    "prompt": "review weekly tasks",
                    "skill_names": ["tasks/sync-notices.md"],
                    "sink_mode": "silent",
                    "notify_policy": "important_only",
                },
                actor="test",
            )

            data = json.loads((root / "runtime" / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(result["action"], "runtime_add_loop")
            self.assertEqual(result["status"], "written")
            self.assertIn("audit", result)
            self.assertIn("weekly_review", [loop["id"] for loop in data["loops"]])

    def test_add_loop_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_json(root / "runtime")
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)

            result = core_runtime.add_loop(
                loop={
                    "id": "backup_check",
                    "enabled": True,
                    "interval_seconds": 300,
                    "prompt": "backup check",
                    "skill_names": [],
                    "sink_mode": "silent",
                },
                actor="test",
            )

            backup_path = Path(result["backup_path"])
            self.assertTrue(backup_path.exists())
            self.assertEqual(backup_path.parent, root / "runtime" / "backups")
            self.assertTrue(list((root / "runtime" / "backups").glob("runtime.*.json")))

    def test_duplicate_loop_id_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_json(root / "runtime")
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)

            with self.assertRaisesRegex(RuntimeError, "duplicate runtime loop id"):
                core_runtime.add_loop(
                    loop={
                        "id": "sync_notices",
                        "enabled": True,
                        "interval_seconds": 30,
                        "prompt": "duplicate",
                        "skill_names": [],
                        "sink_mode": "silent",
                    },
                    actor="test",
                )

            data = json.loads((root / "runtime" / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual([loop["id"] for loop in data["loops"]], ["sync_notices"])
            self.assertEqual(store.runtime_changes(), [])

    def test_invalid_loop_update_validates_before_backup_write_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_path = root / "runtime" / "runtime.json"
            _write_runtime_json(root / "runtime")
            original_text = runtime_path.read_text(encoding="utf-8")
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)

            with self.assertRaisesRegex(RuntimeError, "interval_seconds must be >= 1"):
                core_runtime.update_loop(
                    loop_id="sync_notices",
                    updates={"interval_seconds": 0},
                    actor="test",
                )

            self.assertEqual(runtime_path.read_text(encoding="utf-8"), original_text)
            self.assertFalse((root / "runtime" / "backups").exists())
            self.assertEqual(store.runtime_changes(), [])

    def test_disable_loop_then_list_loops_shows_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_json(root / "runtime")
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)

            core_runtime.disable_loop(loop_id="sync_notices", actor="test")

            loops = {loop["id"]: loop for loop in core_runtime.runtime_list_loops()}
            self.assertFalse(loops["sync_notices"]["enabled"])

    def test_runtime_changes_audit_records_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_json(root / "runtime")
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)

            core_runtime.add_loop(
                loop={
                    "id": "audit_check",
                    "enabled": True,
                    "interval_seconds": 600,
                    "prompt": "audit check",
                    "skill_names": [],
                    "sink_mode": "silent",
                },
                actor="test-agent",
            )

            changes = store.runtime_changes()
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].actor, "test-agent")
            self.assertEqual(changes[0].action, "runtime_add_loop")
            self.assertEqual(changes[0].status, "written")
            self.assertIn("audit_check", changes[0].diff_summary)

    def test_loop_tick_uses_silent_sink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_dir = root / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "runtime.json").write_text(
                json.dumps(
                    {
                        "loops": [
                            {
                                "id": "sync_notices",
                                "enabled": True,
                                "prompt": "loop prompt",
                                "skill_names": ["tasks/sync-notices.md"],
                                "interval_seconds": 1,
                                "sink_mode": "silent",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            _write_test_subskills(root / "sub-skills")
            settings = _settings(root)
            store = Store(settings.app.data_dir / "pkuclaw.db")
            loop = _core_runtime(root, store)

            def fake_popen(command, **kwargs):
                output_path = Path(command[command.index("-o") + 1])
                output_path.write_text("loop done", encoding="utf-8")
                return FakePopen(stdout='{"type":"agent_message","text":"loop"}\n', returncode=0)

            with (
                patch("pkuclaw.code_agents.codex.subprocess.Popen", side_effect=fake_popen),
                patch.object(log.console, "print"),
            ):
                manager = LoopManager(settings=settings, core_runtime=loop)
                try:
                    run_id = manager.tick(reason="manual")
                finally:
                    manager.shutdown(wait=True)

            run = store.get_run(run_id)
            self.assertEqual(run.intent, "loop")
            self.assertEqual(run.status, "succeeded")

    def test_disabled_loop_is_not_scheduled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_json(
                root / "runtime",
                loops=[
                    {
                        "id": "disabled_loop",
                        "enabled": False,
                        "interval_seconds": 1,
                        "prompt": "disabled",
                        "skill_names": [],
                        "sink_mode": "silent",
                    }
                ],
            )
            settings = _settings(root)
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)
            manager = LoopManager(settings=settings, core_runtime=core_runtime)
            try:
                scheduled = manager.run_due_once(now=1.0)
            finally:
                manager.shutdown(wait=True)

            self.assertEqual(scheduled, ())
            self.assertEqual(store.counts_by_status(), {})

    def test_manual_tick_runs_requested_loop_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_json(
                root / "runtime",
                loops=[
                    {
                        "id": "loop_a",
                        "enabled": True,
                        "interval_seconds": 30,
                        "prompt": "prompt a",
                        "skill_names": [],
                        "sink_mode": "silent",
                    },
                    {
                        "id": "loop_b",
                        "enabled": True,
                        "interval_seconds": 30,
                        "prompt": "prompt b",
                        "skill_names": [],
                        "sink_mode": "silent",
                    },
                ],
            )
            settings = _settings(root)
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)
            manager = LoopManager(settings=settings, core_runtime=core_runtime)
            seen_loop_ids: list[str] = []

            def fake_run_agent(run_id, plan, request, sink):
                seen_loop_ids.append(request.channel_context["loop_id"])
                return AgentResult(
                    run_id=run_id,
                    status="succeeded",
                    response_text="ok",
                    session_id=None,
                    result_path=root / "result.md",
                )

            try:
                with patch.object(core_runtime, "run_agent", side_effect=fake_run_agent):
                    run_id = manager.tick(loop_id="loop_b")
            finally:
                manager.shutdown(wait=True)

            self.assertEqual(seen_loop_ids, ["loop_b"])
            metadata = store.get_run_metadata(run_id)
            self.assertEqual(metadata["loop_id"], "loop_b")
            self.assertEqual(store.get_run(run_id).user_text, "prompt b")

    def test_unknown_loop_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_json(root / "runtime")
            settings = _settings(root)
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)
            manager = LoopManager(settings=settings, core_runtime=core_runtime)
            try:
                with self.assertRaisesRegex(RuntimeError, "runtime loop not found"):
                    manager.tick(loop_id="missing_loop")
            finally:
                manager.shutdown(wait=True)

    def test_loop_run_metadata_includes_loop_context_and_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_json(
                root / "runtime",
                loops=[
                    {
                        "id": "targeted_loop",
                        "enabled": True,
                        "interval_seconds": 60,
                        "prompt": "targeted prompt",
                        "skill_names": [],
                        "sink_mode": "silent",
                        "notify_policy": "important_only",
                        "default_channel": "feishu",
                        "default_target_type": "chat_id",
                        "default_target_id": "oc_target",
                    }
                ],
            )
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)

            dispatch = core_runtime.create_loop_run(
                loop_id="targeted_loop",
                scheduled_at="2026-05-05T00:00:00+00:00",
            )

            self.assertIsNotNone(dispatch.run_id)
            self.assertIsNotNone(dispatch.agent_request)
            metadata = store.get_run_metadata(str(dispatch.run_id))
            self.assertEqual(metadata["source"], "loop")
            self.assertEqual(metadata["loop_id"], "targeted_loop")
            self.assertEqual(metadata["notify_policy"], "important_only")
            self.assertEqual(metadata["sink_mode"], "silent")
            self.assertEqual(metadata["scheduled_at"], "2026-05-05T00:00:00+00:00")
            self.assertEqual(metadata["target"]["target_id"], "oc_target")
            self.assertEqual(dispatch.agent_request.channel, "feishu")
            self.assertEqual(
                dispatch.agent_request.channel_context["target"]["target_type"],
                "chat_id",
            )

    def test_prevent_overlap_skips_duplicate_loop_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_json(
                root / "runtime",
                loops=[
                    {
                        "id": "slow_loop",
                        "enabled": True,
                        "interval_seconds": 1,
                        "prompt": "slow",
                        "skill_names": [],
                        "sink_mode": "silent",
                        "prevent_overlap": True,
                    }
                ],
            )
            settings = _settings(root)
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)
            manager = LoopManager(settings=settings, core_runtime=core_runtime)
            started = threading.Event()
            release = threading.Event()

            def fake_run_agent(run_id, plan, request, sink):
                started.set()
                release.wait(timeout=2)
                return AgentResult(
                    run_id=run_id,
                    status="succeeded",
                    response_text="ok",
                    session_id=None,
                    result_path=root / "result.md",
                )

            try:
                with patch.object(core_runtime, "run_agent", side_effect=fake_run_agent):
                    first_run_id = manager.tick(loop_id="slow_loop", wait=False)
                    self.assertTrue(started.wait(timeout=1))
                    with self.assertRaisesRegex(RuntimeError, "already running"):
                        manager.tick(loop_id="slow_loop", wait=False)
                    release.set()
                    _wait_for_loop_manager_idle(manager)
            finally:
                release.set()
                manager.shutdown(wait=True)

            self.assertIsNotNone(first_run_id)
            self.assertEqual(store.counts_by_status(), {"queued": 1})

    def test_multi_loop_scheduler_does_not_block_on_long_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_json(
                root / "runtime",
                loops=[
                    {
                        "id": "slow_loop",
                        "enabled": True,
                        "interval_seconds": 60,
                        "prompt": "slow",
                        "skill_names": [],
                        "sink_mode": "silent",
                    },
                    {
                        "id": "fast_loop",
                        "enabled": True,
                        "interval_seconds": 60,
                        "prompt": "fast",
                        "skill_names": [],
                        "sink_mode": "silent",
                    },
                ],
            )
            settings = _settings(root)
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)
            manager = LoopManager(settings=settings, core_runtime=core_runtime)
            slow_started = threading.Event()
            fast_started = threading.Event()
            release_slow = threading.Event()

            def fake_run_agent(run_id, plan, request, sink):
                loop_id = request.channel_context["loop_id"]
                if loop_id == "slow_loop":
                    slow_started.set()
                    release_slow.wait(timeout=2)
                if loop_id == "fast_loop":
                    fast_started.set()
                return AgentResult(
                    run_id=run_id,
                    status="succeeded",
                    response_text=f"{loop_id} ok",
                    session_id=None,
                    result_path=root / f"{loop_id}.md",
                )

            try:
                with patch.object(core_runtime, "run_agent", side_effect=fake_run_agent):
                    scheduled = manager.run_due_once(now=10.0)
                    self.assertEqual(len(scheduled), 2)
                    self.assertTrue(slow_started.wait(timeout=1))
                    self.assertTrue(fast_started.wait(timeout=1))
                    release_slow.set()
                    _wait_for_loop_manager_idle(manager)
            finally:
                release_slow.set()
                manager.shutdown(wait=True)

    def test_loop_interval_seconds_controls_independent_next_due(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_json(
                root / "runtime",
                loops=[
                    {
                        "id": "fast_loop",
                        "enabled": True,
                        "interval_seconds": 30,
                        "prompt": "fast",
                        "skill_names": [],
                        "sink_mode": "silent",
                    },
                    {
                        "id": "slow_loop",
                        "enabled": True,
                        "interval_seconds": 60,
                        "prompt": "slow",
                        "skill_names": [],
                        "sink_mode": "silent",
                    },
                ],
            )
            settings = _settings(root)
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)
            manager = LoopManager(settings=settings, core_runtime=core_runtime)

            def fake_run_agent(run_id, plan, request, sink):
                return AgentResult(
                    run_id=run_id,
                    status="succeeded",
                    response_text="ok",
                    session_id=None,
                    result_path=root / "result.md",
                )

            try:
                with patch.object(core_runtime, "run_agent", side_effect=fake_run_agent):
                    self.assertEqual(len(manager.run_due_once(now=100.0)), 2)
                    _wait_for_loop_manager_idle(manager)
                    self.assertEqual(manager.next_due_by_loop["fast_loop"], 130.0)
                    self.assertEqual(manager.next_due_by_loop["slow_loop"], 160.0)
                    self.assertEqual(manager.run_due_once(now=129.0), ())
                    self.assertEqual(len(manager.run_due_once(now=130.0)), 1)
                    _wait_for_loop_manager_idle(manager)
            finally:
                manager.shutdown(wait=True)


class RuntimeBootstrapTests(unittest.TestCase):
    def test_core_runtime_services_own_bootstrap_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root)

            services = build_core_runtime_services(settings, repo_root=root)
            try:
                self.assertIs(services.core_runtime.store, services.store)
                self.assertIs(
                    services.core_runtime.runtime_config,
                    services.runtime_config,
                )
                self.assertIs(
                    services.core_runtime.agent_wrapper,
                    services.agent_wrapper,
                )
                self.assertIs(services.core_runtime.run_executor, services.run_executor)
                self.assertEqual(dict(services.core_runtime.channel_backends), {})
            finally:
                services.run_executor.shutdown(cancel_futures=True)
                services.callback_executor.shutdown(cancel_futures=True)

    def test_mcp_handler_channel_send_text_uses_core_runtime_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root)
            services = build_core_runtime_services(settings, repo_root=root)
            backend = RecordingOutboundBackend(channel="feishu")
            services.core_runtime.register_channel_backend(backend)
            handler = DaemonMcpToolHandler(
                core_runtime=services.core_runtime,
                default_channel="feishu",
            )

            try:
                result = handler.call_tool(
                    "channel_send_text",
                    {"target_id": "oc_chat", "text": "hello via core"},
                )

                self.assertTrue(result.ok)
                self.assertEqual(result.data["message_id"], "om_recorded")
                self.assertEqual(
                    backend.calls,
                    [("send_text", "feishu", "chat_id", "oc_chat", "hello via core")],
                )
                self.assertIn("feishu", services.core_runtime.channel_backends)
            finally:
                services.run_executor.shutdown(cancel_futures=True)
                services.callback_executor.shutdown(cancel_futures=True)

    def test_mcp_tools_list_includes_channel_and_runtime_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            core_runtime = _core_runtime(Path(tmp), store)
            handler = DaemonMcpToolHandler(core_runtime=core_runtime)

            status, response = handle_mcp_request(
                handler,
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )

            self.assertEqual(status, 200)
            names = {tool["name"] for tool in response["result"]["tools"]}
            self.assertIn("channel_send_text", names)
            self.assertIn("channel_send_card", names)
            self.assertIn("channel_send_image", names)
            self.assertIn("channel_update_card", names)
            self.assertIn("runtime_get_status", names)
            self.assertIn("runtime_get_config", names)
            self.assertIn("runtime_list_loops", names)
            self.assertIn("runtime_list_recent_runs", names)
            self.assertIn("runtime_get_run", names)
            self.assertIn("runtime_add_loop", names)
            self.assertTrue(all("pku3b" not in name for name in names))

    def test_mcp_runtime_get_status_returns_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            core_runtime = _core_runtime(Path(tmp), store)
            handler = DaemonMcpToolHandler(core_runtime=core_runtime)

            status, response = handle_mcp_request(
                handler,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "runtime_get_status",
                        "arguments": {},
                    },
                },
            )

            self.assertEqual(status, 200)
            self.assertFalse(response["result"]["isError"])
            payload = json.loads(response["result"]["content"][0]["text"])
            self.assertTrue(payload["ok"])
            self.assertIn("runtime_config_path", payload["data"])
            self.assertIn("run_counts", payload["data"])

    def test_mcp_unknown_tool_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            core_runtime = _core_runtime(Path(tmp), store)
            handler = DaemonMcpToolHandler(core_runtime=core_runtime)

            status, response = handle_mcp_request(
                handler,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "does_not_exist", "arguments": {}},
                },
            )

            self.assertEqual(status, 200)
            self.assertIn("error", response)
            self.assertIn("unknown tool", response["error"]["message"])

    def test_mcp_runtime_write_tool_calls_core_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_json(root / "runtime")
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)
            handler = DaemonMcpToolHandler(core_runtime=core_runtime)

            result = handler.call_tool("runtime_disable_loop", {"loop_id": "sync_notices"})

            self.assertTrue(result.ok)
            self.assertEqual(result.data["action"], "runtime_disable_loop")
            self.assertEqual(result.data["audit"]["status"], "recorded")
            loops = {loop["id"]: loop for loop in core_runtime.runtime_list_loops()}
            self.assertFalse(loops["sync_notices"]["enabled"])
            self.assertEqual(store.runtime_changes()[0].action, "runtime_disable_loop")

    def test_mcp_layer_has_no_direct_feishu_backend_imports(self) -> None:
        forbidden_modules = {
            "pkuclaw.channels.feishu",
            "pkuclaw.channels.feishu.tools",
            "pkuclaw.channels.feishu.gateway",
            "pkuclaw.channels.feishu.handlers",
        }
        forbidden_names = {
            "FeishuChannelOutboundBackend",
            "FeishuRealtimeGateway",
            "FeishuEventHandlers",
            "FeishuCardKitClient",
        }
        for source_path in Path("pkuclaw/mcp").glob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            imported_modules: set[str] = set()
            imported_names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.add(node.module)
                    imported_names.update(alias.name for alias in node.names)
                elif isinstance(node, ast.Import):
                    imported_names.update(alias.name for alias in node.names)

            self.assertTrue(imported_modules.isdisjoint(forbidden_modules), source_path)
            self.assertTrue(imported_names.isdisjoint(forbidden_names), source_path)

    def test_agent_wrapper_has_no_runtime_write_or_daemon_control_calls(self) -> None:
        source_path = Path("pkuclaw/agents/wrapper.py")
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        forbidden_modules = {
            "pkuclaw.loop",
            "pkuclaw.mcp.server",
            "pkuclaw.channels.feishu.gateway",
            "pkuclaw.channels.feishu.handlers",
        }
        forbidden_names = {"LoopManager", "DaemonMcpServer", "FeishuEventHandlers"}
        forbidden_call_names = {
            "write_runtime_patch",
            "add_loop",
            "update_loop",
            "enable_loop",
            "disable_loop",
            "backup_current",
            "atomic_write_json",
            "attach_loop_manager",
            "serve_forever",
        }
        imported_modules: set[str] = set()
        imported_names: set[str] = set()
        call_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    call_names.add(func.attr)
                elif isinstance(func, ast.Name):
                    call_names.add(func.id)

        self.assertTrue(imported_modules.isdisjoint(forbidden_modules))
        self.assertTrue(imported_names.isdisjoint(forbidden_names))
        self.assertTrue(call_names.isdisjoint(forbidden_call_names))

    def test_loop_manager_does_not_import_or_call_agent_wrapper(self) -> None:
        source_path = Path("pkuclaw/loop.py")
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules: set[str] = set()
        names: set[str] = set()
        attributes: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                attributes.add(node.attr)

        self.assertNotIn("pkuclaw.agents.wrapper", imported_modules)
        self.assertNotIn("AgentWrapper", names)
        self.assertNotIn("agent_wrapper", attributes)

    def test_feishu_gateway_stays_transport_only(self) -> None:
        source_path = Path("pkuclaw/channels/feishu/gateway.py")
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        forbidden_modules = {
            "pkuclaw.agents",
            "pkuclaw.agents.wrapper",
            "pkuclaw.core.store",
            "pkuclaw.loop",
            "pkuclaw.mcp",
            "pkuclaw.mcp.server",
            "pkuclaw.runtime_config",
        }
        forbidden_names = {
            "AgentWrapper",
            "DaemonMcpServer",
            "LoopManager",
            "RuntimeConfigStore",
            "Store",
        }
        imported_modules: set[str] = set()
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)

        self.assertTrue(imported_modules.isdisjoint(forbidden_modules))
        self.assertTrue(imported_names.isdisjoint(forbidden_names))

    def test_feishu_realtime_bootstrap_path_disables_mcp_and_loop_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root)
            backend = RecordingOutboundBackend(channel="feishu")
            fake_gateway = FakeObject(
                channel="feishu",
                channel_backend=backend,
                start=lambda: None,
            )
            with (
                patch(
                    "pkuclaw.runtime.bootstrap.build_feishu_realtime_gateway",
                    return_value=fake_gateway,
                ) as gateway_builder,
                patch("pkuclaw.runtime.bootstrap._start_mcp_thread") as mcp_start,
                patch("pkuclaw.runtime.bootstrap._start_loop_manager") as loop_start,
            ):
                bootstrap = build_runtime_bootstrap(
                    settings,
                    enable_loop=False,
                    enable_mcp=False,
                )

            try:
                gateway_builder.assert_called_once()
                mcp_start.assert_not_called()
                loop_start.assert_not_called()
                self.assertIsNone(bootstrap.loop_manager)
                self.assertIsNone(bootstrap.mcp_server)
                self.assertEqual(bootstrap.threads, ())
                self.assertIn("feishu", bootstrap.services.core_runtime.channel_backends)
            finally:
                bootstrap.services.run_executor.shutdown(cancel_futures=True)
                bootstrap.services.callback_executor.shutdown(cancel_futures=True)


class FeishuOutboxTests(unittest.TestCase):
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


def _write_test_subskills(root: Path) -> None:
    files = {
        "runtime/codex-subagent.md": "# Codex runtime\n",
        "tasks/write-notes.md": "# Write notes\n",
        "tasks/do-homework.md": "# Do homework\n",
        "tasks/sync-notices.md": "# Sync notices\n",
        "tools/pdf-reader.md": "# PDF reader\n",
        "tools/pku3b-setup.md": "# pku3b setup\n",
        "tools/data-parser.md": "# Data parser\n",
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _write_skills_json(
    runtime_dir: Path,
    *,
    skills: list[dict] | None = None,
) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 1,
        "skills": skills
        or [
            {
                "name": "runtime/codex-subagent.md",
                "intent": "runtime",
                "dependencies": [],
                "allowed_sources": ["realtime", "loop", "mcp", "manual", "system"],
                "requires_confirmation": False,
            },
            {
                "name": "tasks/sync-notices.md",
                "intent": "sync",
                "dependencies": ["tools/pku3b-setup.md", "tools/data-parser.md"],
                "allowed_sources": ["realtime", "loop"],
                "requires_confirmation": False,
            },
            {
                "name": "tasks/do-homework.md",
                "intent": "homework",
                "dependencies": ["tools/pdf-reader.md", "tools/pku3b-setup.md"],
                "allowed_sources": ["realtime"],
                "requires_confirmation": True,
            },
            {
                "name": "tasks/write-notes.md",
                "intent": "notes",
                "dependencies": ["tools/pdf-reader.md"],
                "allowed_sources": ["realtime", "loop"],
                "requires_confirmation": False,
            },
            {
                "name": "tools/pku3b-setup.md",
                "intent": "tool",
                "dependencies": [],
                "allowed_sources": ["realtime", "loop", "mcp", "manual", "system"],
                "requires_confirmation": False,
            },
            {
                "name": "tools/data-parser.md",
                "intent": "tool",
                "dependencies": [],
                "allowed_sources": ["realtime", "loop", "mcp", "manual", "system"],
                "requires_confirmation": False,
            },
            {
                "name": "tools/pdf-reader.md",
                "intent": "tool",
                "dependencies": [],
                "allowed_sources": ["realtime", "loop", "mcp", "manual", "system"],
                "requires_confirmation": False,
            },
        ],
    }
    (runtime_dir / "skills.json").write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )


def _feishu_chat_target() -> ChannelTarget:
    return ChannelTarget(
        channel="feishu",
        target_type="chat_id",
        target_id="oc_chat",
    )


def _element_tags(card: dict) -> set[str]:
    tags: set[str] = set()

    def collect(value) -> None:
        if isinstance(value, dict):
            tag = value.get("tag")
            if isinstance(tag, str):
                tags.add(tag)
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(card)
    return tags


def _markdown_contents(card: dict) -> list[str]:
    contents: list[str] = []

    def collect(value) -> None:
        if isinstance(value, dict):
            if value.get("tag") == "markdown":
                content = value.get("content")
                if isinstance(content, str):
                    contents.append(content)
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(card)
    return contents


def _buttons(card: dict) -> list[dict]:
    buttons: list[dict] = []

    def collect(value) -> None:
        if isinstance(value, dict):
            if value.get("tag") == "button":
                buttons.append(value)
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(card)
    return buttons


class CapturingSink:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def emit(self, event: AgentEvent) -> None:
        self.events.append(event)


class RecordingOutboundBackend:
    def __init__(self, *, channel: str) -> None:
        self.channel = channel
        self.calls: list[tuple] = []

    def send_text(self, *, target: ChannelTarget, text: str) -> ChannelOutboundResult:
        self.calls.append(
            ("send_text", target.channel, target.target_type, target.target_id, text)
        )
        return ChannelOutboundResult(
            ok=True,
            message="recorded text",
            target=target,
            external_message_id="om_recorded",
            external_card_id="card_recorded",
            data={"message_id": "om_recorded", "card_id": "card_recorded"},
        )

    def send_card(
        self,
        *,
        target: ChannelTarget,
        card: dict,
    ) -> ChannelOutboundResult:
        self.calls.append(("send_card", target.channel, target.target_id, card))
        return ChannelOutboundResult(ok=True, message="recorded card", target=target)

    def send_image(
        self,
        *,
        target: ChannelTarget,
        image_path: str,
    ) -> ChannelOutboundResult:
        self.calls.append(("send_image", target.channel, target.target_id, image_path))
        return ChannelOutboundResult(ok=True, message="recorded image", target=target)

    def update_card(
        self,
        *,
        card_id: str,
        card: dict,
        sequence: int,
    ) -> ChannelOutboundResult:
        self.calls.append(("update_card", card_id, card, sequence))
        return ChannelOutboundResult(ok=True, message="recorded update")


class FakePopen:
    def __init__(self, *, stdout: str, returncode: int) -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(stdout)
        self.returncode = returncode

    def poll(self) -> int:
        return self.returncode

    def wait(self, timeout: int | None = None) -> int:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


class FakeLark:
    UTF_8 = "utf-8"


class FakeResponseData:
    def __init__(
        self,
        *,
        message_id: str | None = None,
        card_id: str | None = None,
    ) -> None:
        self.message_id = message_id
        self.card_id = card_id


class FakeResponse:
    code = 0
    msg = "ok"
    raw = None

    def __init__(self, data: FakeResponseData | None = None) -> None:
        self.data = data or FakeResponseData()

    def success(self) -> bool:
        return True

    def get_log_id(self) -> str:
        return "log-id"


class FakeMessageResource:
    def __init__(self) -> None:
        self.created = None

    def create(self, request):
        self.created = request
        return FakeResponse(FakeResponseData(message_id="om_1"))


class FakeCardResource:
    def __init__(self) -> None:
        self.created = None
        self.updated = None
        self.update_count = 0

    def create(self, request):
        self.created = request
        return FakeResponse(FakeResponseData(card_id="card_1"))

    def update(self, request):
        self.updated = request
        self.update_count += 1
        return FakeResponse()


class FakeFeishuApi:
    def __init__(self) -> None:
        self.im = FakeObject(
            v1=FakeObject(
                message=FakeMessageResource(),
            )
        )
        self.cardkit = FakeObject(
            v1=FakeObject(
                card=FakeCardResource(),
            )
        )


class FakeObject:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class FakeBuilder:
    def __init__(self, target) -> None:
        self.target = target

    def receive_id_type(self, value):
        self.target.receive_id_type = value
        return self

    def receive_id(self, value):
        self.target.receive_id = value
        return self

    def msg_type(self, value):
        self.target.msg_type = value
        return self

    def content(self, value):
        self.target.content = value
        return self

    def request_body(self, value):
        self.target.body = value
        return self

    def message_id(self, value):
        self.target.message_id = value
        return self

    def card_id(self, value):
        self.target.card_id = value
        return self

    def type(self, value):
        self.target.type = value
        return self

    def data(self, value):
        self.target.data = value
        return self

    def card(self, value):
        self.target.card = value
        return self

    def uuid(self, value):
        self.target.uuid = value
        return self

    def sequence(self, value):
        self.target.sequence = value
        return self

    def build(self):
        return self.target


class FakeCreateMessageRequest:
    @staticmethod
    def builder() -> FakeBuilder:
        return FakeBuilder(FakeObject())


class FakeCreateMessageRequestBody:
    @staticmethod
    def builder() -> FakeBuilder:
        return FakeBuilder(FakeObject())


class FakeCreateCardRequest:
    @staticmethod
    def builder() -> FakeBuilder:
        return FakeBuilder(FakeObject())


class FakeCreateCardRequestBody:
    @staticmethod
    def builder() -> FakeBuilder:
        return FakeBuilder(FakeObject())


class FakeUpdateCardRequest:
    @staticmethod
    def builder() -> FakeBuilder:
        return FakeBuilder(FakeObject())


class FakeUpdateCardRequestBody:
    @staticmethod
    def builder() -> FakeBuilder:
        return FakeBuilder(FakeObject())


class FakeCardModel:
    @staticmethod
    def builder() -> FakeBuilder:
        return FakeBuilder(FakeObject())


def _fake_feishu_cardkit_client(fake_api: FakeFeishuApi) -> FeishuCardKitClient:
    return FeishuCardKitClient(
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


def _write_runtime_json(
    runtime_dir: Path,
    *,
    loops: list[dict] | None = None,
    permissions: dict | None = None,
) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 1,
        "agent": {
            "provider": "codex",
            "mode": "standard",
            "model": "",
            "reasoning_effort": "",
        },
        "codex": {
            "sandbox": "workspace-write",
            "timeout_seconds": 1800,
        },
        "loops": loops
        or [
            {
                "id": "sync_notices",
                "enabled": True,
                "interval_seconds": 900,
                "prompt": "sync notices",
                "skill_names": ["tasks/sync-notices.md"],
                "sink_mode": "silent",
                "notify_policy": "important_only",
            }
        ],
        "prompt": {
            "fragment_paths": [],
            "default_skill_names": [],
        },
        "notifications": {
            "policy": "important_only",
        },
        "permissions": permissions
        or {
            "agent_can_update_runtime": True,
            "agent_can_add_loop": True,
            "agent_can_modify_boot_config": False,
        },
    }
    (runtime_dir / "runtime.json").write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )


def _core_runtime(root: Path, store: Store) -> CoreRuntime:
    settings = _settings(root)
    runtime_config = RuntimeConfigStore(root / "runtime")
    return CoreRuntime(
        store=store,
        agent_wrapper=AgentWrapper(
            settings=settings,
            store=store,
            runtime_config=runtime_config,
            repo_root=root,
        ),
        runtime_config=runtime_config,
    )


def _agent_request(
    *,
    conversation_id: str,
    text: str,
    intent: str,
    skill_names: tuple[str, ...],
):
    from pkuclaw.core.models import AgentRunRequest

    return AgentRunRequest(
        source="realtime",
        conversation_id=conversation_id,
        text=text,
        intent=intent,
        skill_names=skill_names,
        channel="feishu",
        sender_id="open-1",
        sink_mode="streaming",
    )


def _settings(root: Path) -> Settings:
    return Settings(
        config_path=root / "config.toml",
        app=AppConfig(
            name="test",
            data_dir=root / "data",
            runtime_config_dir=root / "runtime",
            timezone="Asia/Shanghai",
        ),
        feishu=FeishuConfig(
            app_id="cli_test",
            app_secret=None,
            app_secret_env="FEISHU_APP_SECRET",
            event_mode="websocket",
        ),
        agent=AgentConfig(provider="codex"),
        codex=CodexConfig(
            bin="codex",
            sandbox="workspace-write",
            model=None,
            timeout_seconds=30,
            max_concurrent_runs=1,
        ),
        monitor=MonitorConfig(
            scan_interval_seconds=900,
            enable_assignments=True,
            enable_announcements=True,
            enable_replays=True,
            enable_grades=False,
        ),
        mcp=McpConfig(host="127.0.0.1", port=8765),
    )


def _wait_for_loop_manager_idle(manager: LoopManager, *, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not manager._active_by_loop:  # noqa: SLF001 - assert scheduler state in tests
            return
        time.sleep(0.01)
    raise AssertionError("LoopManager did not become idle")


if __name__ == "__main__":
    unittest.main()
