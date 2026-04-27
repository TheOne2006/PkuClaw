from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pkuclaw.agents import AgentWrapper
from pkuclaw.code_agents.artifacts import codex_trace_events
from pkuclaw.code_agents.subskills import render_subskills, resolve_subskill_names
from pkuclaw.channels.feishu.cards import (
    FeishuCardKitClient,
    FeishuCardRenderer,
    FeishuRunCardSink,
)
from pkuclaw.channels.feishu.tools import FeishuChannelToolBackend
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
from pkuclaw.core.app import CoreLoop
from pkuclaw.core.models import AgentEvent, ChannelMessage
from pkuclaw.core.router import classify_message
from pkuclaw.core.store import Store
from pkuclaw.loop import LoopThread
from pkuclaw.runtime_config import RuntimeConfigLoader


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


class StoreAndCoreLoopTests(unittest.TestCase):
    def test_conversation_mode_and_local_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            loop = _core_loop(Path(tmp), store)

            dispatch = loop.ingest(
                ChannelMessage(
                    channel="feishu",
                    conversation_id="feishu:user:open-1",
                    sender_id="open-1",
                    text="",
                    event_key="mode:fast",
                )
            )

            self.assertTrue(dispatch.handled_locally)
            self.assertIsNone(dispatch.run_id)
            self.assertIn("Fast", dispatch.reply_text)
            conversation = store.ensure_conversation("feishu:user:open-1")
            self.assertEqual(conversation.agent_settings.mode, "fast")

            dispatch = loop.ingest(
                ChannelMessage(
                    channel="feishu",
                    conversation_id="feishu:user:open-1",
                    sender_id="open-1",
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
            loop = _core_loop(Path(tmp), store)

            dispatch = loop.ingest(
                ChannelMessage(
                    channel="feishu",
                    conversation_id="feishu:user:open-1",
                    sender_id="open-1",
                    text="你好",
                )
            )

            self.assertFalse(dispatch.handled_locally)
            self.assertIsNotNone(dispatch.run_id)
            self.assertIsNotNone(dispatch.agent_request)
            self.assertEqual(store.counts_by_status(), {"queued": 1})

    def test_unknown_event_key_does_not_create_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            loop = _core_loop(Path(tmp), store)

            dispatch = loop.ingest(
                ChannelMessage(
                    channel="feishu",
                    conversation_id="feishu:user:open-1",
                    sender_id="open-1",
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
                "路径 `configs/runtime/agent.json`\n\n"
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
        self.assertIn("路径 configs/runtime/agent.json", markdown)
        self.assertNotIn("路径 `configs/runtime/agent.json`", markdown)
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
                chat_id="oc_chat",
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
    def test_wrapper_builds_prompt_and_codex_persists_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_dir = root / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "agent.json").write_text(
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
                runtime_config=RuntimeConfigLoader(runtime_dir),
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
                    'mcp_servers.pkuclaw_channel_tools.url="http://127.0.0.1:8765/mcp"',
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
            self.assertIn("Agent-Wrapper owns prompt construction", prompt)
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
            loader = RuntimeConfigLoader(runtime_dir)

            config = loader.read()

            self.assertEqual(config.agent.provider, "codex")
            self.assertTrue(config.warnings)
            self.assertIn("fallback", config.warnings[0])

    def test_loop_tick_uses_silent_sink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_dir = root / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "agent.json").write_text(
                json.dumps(
                    {
                        "loop": {
                            "prompt": "loop prompt",
                            "skill_names": ["tasks/sync-notices.md"],
                            "interval_seconds": 1,
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            _write_test_subskills(root / "sub-skills")
            settings = _settings(root)
            store = Store(settings.app.data_dir / "pkuclaw.db")
            loop = _core_loop(root, store)

            def fake_popen(command, **kwargs):
                output_path = Path(command[command.index("-o") + 1])
                output_path.write_text("loop done", encoding="utf-8")
                return FakePopen(stdout='{"type":"agent_message","text":"loop"}\n', returncode=0)

            with (
                patch("pkuclaw.code_agents.codex.subprocess.Popen", side_effect=fake_popen),
                patch.object(log.console, "print"),
            ):
                run_id = LoopThread(settings=settings, core_loop=loop).tick(reason="manual")

            run = store.get_run(run_id)
            self.assertEqual(run.intent, "loop")
            self.assertEqual(run.status, "succeeded")


class ChannelToolTests(unittest.TestCase):
    def test_feishu_channel_tools_send_text_and_report_image_gap(self) -> None:
        fake_api = FakeFeishuApi()
        backend = FeishuChannelToolBackend(
            client=_fake_feishu_cardkit_client(fake_api),
            renderer=FeishuCardRenderer(),
        )

        result = backend.channel_send_text(target_id="oc_chat", text="hello")
        image_result = backend.channel_send_image(
            target_id="oc_chat",
            image_path="image.png",
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.data["message_id"], "om_1")
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


def _core_loop(root: Path, store: Store) -> CoreLoop:
    settings = _settings(root)
    runtime_config = RuntimeConfigLoader(root / "runtime")
    return CoreLoop(
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


if __name__ == "__main__":
    unittest.main()
