from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from pkuclaw.backbone import TeachingBackbone
from pkuclaw.code_agents.codex import CodexAgent
from pkuclaw.channels.feishu_cards import (
    FeishuCardRenderer,
    FeishuMessageClient,
    FeishuRunCardSink,
)
from pkuclaw.config import (
    AppConfig,
    CodexConfig,
    CodeAgentConfig,
    FeishuConfig,
    MonitorConfig,
    Pku3bConfig,
    Settings,
)
from pkuclaw.core import logging as log
from pkuclaw.core.app import CoreLoop
from pkuclaw.core.models import ChannelMessage, CodeAgentEvent
from pkuclaw.core.router import classify_message
from pkuclaw.core.store import Store
from pkuclaw.runtime_config import RuntimeConfigLoader


class RouterTests(unittest.TestCase):
    def test_classifies_notes(self) -> None:
        plan = classify_message("帮我继续多智能体基础的笔记")
        self.assertEqual(plan.intent, "notes")
        self.assertIn("notes.write", plan.capability_names)

    def test_classifies_homework(self) -> None:
        plan = classify_message("量子力学 hw5 先规划一下，不要提交")
        self.assertEqual(plan.intent, "homework")
        self.assertIn("homework.plan", plan.capability_names)

    def test_classifies_sync(self) -> None:
        plan = classify_message("看看这周有什么要交")
        self.assertEqual(plan.intent, "sync")
        self.assertIn("notice.summarize", plan.capability_names)


class StoreAndCoreLoopTests(unittest.TestCase):
    def test_conversation_mode_and_local_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            loop = CoreLoop(
                store=store,
                code_agent=_fake_code_agent(Path(tmp), store),
                runtime_config=RuntimeConfigLoader(Path(tmp) / "runtime"),
            )

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
            loop = CoreLoop(
                store=store,
                code_agent=_fake_code_agent(Path(tmp), store),
                runtime_config=RuntimeConfigLoader(Path(tmp) / "runtime"),
            )

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
            self.assertEqual(store.counts_by_status(), {"queued": 1})

    def test_unknown_event_key_does_not_create_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            loop = CoreLoop(
                store=store,
                code_agent=_fake_code_agent(Path(tmp), store),
                runtime_config=RuntimeConfigLoader(Path(tmp) / "runtime"),
            )

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
    def test_renderer_builds_interactive_run_card(self) -> None:
        card = FeishuCardRenderer().run_progress_card(
            run_id="abc123",
            user_text="帮我整理一下",
            ack="开始处理",
            phase="running",
            events=["启动 Codex", "生成回复中"],
            agent_context={
                "provider": "codex",
                "mode": "Fast",
                "model": "gpt-test",
            },
            started_at=0.0,
        )

        self.assertTrue(card["config"]["wide_screen_mode"])
        self.assertTrue(card["config"]["update_multi"])
        self.assertEqual(card["header"]["title"]["content"], "PkuClaw 正在处理")
        self.assertEqual(card["elements"][-1]["tag"], "action")

    def test_message_client_sends_and_patches_card(self) -> None:
        fake_api = FakeFeishuApi()
        client = FeishuMessageClient(
            lark=FakeLark(),
            client=fake_api,
            create_message_request=FakeCreateMessageRequest,
            create_message_request_body=FakeCreateMessageRequestBody,
            patch_message_request=FakePatchMessageRequest,
            patch_message_request_body=FakePatchMessageRequestBody,
        )

        message_id = client.send_card(
            receive_id_type="chat_id",
            receive_id="oc_chat",
            card={"config": {}, "elements": []},
        )
        client.patch_card(message_id=message_id, card={"config": {}, "elements": []})

        self.assertEqual(message_id, "om_1")
        self.assertEqual(fake_api.im.v1.message.created.body.msg_type, "interactive")
        self.assertEqual(fake_api.im.v1.message.patched.message_id, "om_1")
        json.loads(fake_api.im.v1.message.created.body.content)
        json.loads(fake_api.im.v1.message.patched.body.content)

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
                client=_fake_feishu_message_client(fake_api),
                renderer=FeishuCardRenderer(),
                store=store,
                chat_id="oc_chat",
                run_id=run.run_id,
                user_text=run.user_text,
                ack="开始处理",
                agent_context={"provider": "codex", "mode": "Fast"},
            )

            sink.start()
            sink.emit(
                CodeAgentEvent(
                    run_id=run.run_id,
                    kind="progress",
                    phase="running",
                    message="启动 Codex",
                )
            )
            sink.emit(
                CodeAgentEvent(
                    run_id=run.run_id,
                    kind="final",
                    phase="finished",
                    message="hello",
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
            self.assertEqual(fake_api.im.v1.message.patch_count, 2)


class CodexAgentTests(unittest.TestCase):
    def test_agent_persists_result_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_dir = root / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "agent.toml").write_text(
                """
[code_agent]
mode = "fast"
model = "gpt-test"

[codex]
sandbox = "read-only"
timeout_seconds = 60
""",
                encoding="utf-8",
            )
            settings = _settings(root)
            store = Store(settings.app.data_dir / "pkuclaw.db")
            plan = classify_message("你好")
            run = store.create_run(
                conversation_id="feishu:user:open-1",
                user_text="你好",
                intent=plan.intent,
            )

            def fake_popen(command, **kwargs):
                output_path = Path(command[command.index("-o") + 1])
                output_path.write_text("## 回复用户\nhello\n", encoding="utf-8")
                self.assertIn("-c", command)
                self.assertIn('model_reasoning_effort="low"', command)
                self.assertIn("-m", command)
                self.assertIn("gpt-test", command)
                self.assertIn("read-only", command)
                return FakePopen(
                    stdout='{"thread_id":"thread-abc","text":"hello"}\n',
                    returncode=0,
                )

            sink = CapturingSink()
            with (
                patch("pkuclaw.code_agents.codex.subprocess.Popen", side_effect=fake_popen),
                patch.object(log.console, "print"),
            ):
                result = CodexAgent(
                    settings=settings,
                    store=store,
                    runtime_config=RuntimeConfigLoader(runtime_dir),
                    repo_root=root,
                ).run(run, plan, sink)

            self.assertEqual(result.status, "succeeded")
            self.assertEqual(result.session_id, "thread-abc")
            self.assertTrue(result.result_path.exists())
            self.assertTrue((settings.app.data_dir / "code_agent_runs").exists())
            self.assertIn("started", [event.kind for event in sink.events])
            self.assertIn("final", [event.kind for event in sink.events])
            conversation = store.ensure_conversation("feishu:user:open-1")
            self.assertEqual(conversation.agent_session_id, "thread-abc")


class TeachingBackboneTests(unittest.TestCase):
    def test_collects_snapshot_from_pku3b(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = TeachingBackbone(
                pku3b=FakePku3b(),
                snapshot_dir=Path(tmp) / "snapshots",
            ).collect_snapshot()

            self.assertTrue(snapshot.path.exists())
            self.assertIn("assignment", snapshot.assignments_raw)
            self.assertIn("announcement", snapshot.announcements_raw)
            self.assertIn("course_table", snapshot.course_table_raw)


class FakePku3b:
    def run(self, *args: str) -> CompletedProcess[str]:
        key = " ".join(args)
        return CompletedProcess(args, 0, stdout=f"{key}: assignment announcement course_table", stderr="")


class CapturingSink:
    def __init__(self) -> None:
        self.events: list[CodeAgentEvent] = []

    def emit(self, event: CodeAgentEvent) -> None:
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
    message_id = "om_1"


class FakeResponse:
    code = 0
    msg = "ok"
    raw = None
    data = FakeResponseData()

    def success(self) -> bool:
        return True

    def get_log_id(self) -> str:
        return "log-id"


class FakeMessageResource:
    def __init__(self) -> None:
        self.created = None
        self.patched = None
        self.patch_count = 0

    def create(self, request):
        self.created = request
        return FakeResponse()

    def patch(self, request):
        self.patched = request
        self.patch_count += 1
        return FakeResponse()


class FakeFeishuApi:
    def __init__(self) -> None:
        self.im = FakeObject(
            v1=FakeObject(
                message=FakeMessageResource(),
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


class FakePatchMessageRequest:
    @staticmethod
    def builder() -> FakeBuilder:
        return FakeBuilder(FakeObject())


class FakePatchMessageRequestBody:
    @staticmethod
    def builder() -> FakeBuilder:
        return FakeBuilder(FakeObject())


def _fake_feishu_message_client(fake_api: FakeFeishuApi) -> FeishuMessageClient:
    return FeishuMessageClient(
        lark=FakeLark(),
        client=fake_api,
        create_message_request=FakeCreateMessageRequest,
        create_message_request_body=FakeCreateMessageRequestBody,
        patch_message_request=FakePatchMessageRequest,
        patch_message_request_body=FakePatchMessageRequestBody,
    )


def _fake_code_agent(root: Path, store: Store) -> CodexAgent:
    return CodexAgent(
        settings=_settings(root),
        store=store,
        runtime_config=RuntimeConfigLoader(root / "runtime"),
        repo_root=root,
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
        pku3b=Pku3bConfig(bin=root / "pku3b", source_dir=root / "pku3b-src"),
        code_agent=CodeAgentConfig(provider="codex"),
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
    )


if __name__ == "__main__":
    unittest.main()
