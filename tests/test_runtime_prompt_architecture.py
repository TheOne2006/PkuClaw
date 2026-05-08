from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pkuclaw.agents.artifacts import build_codex_artifact_detail
from pkuclaw.agents.providers.codex import CodexAgent
from pkuclaw.agents.wrapper import AgentWrapper
from pkuclaw.channels.base import (
    ChannelInboundMessage,
    ChannelOutboundResult,
    ChannelTarget,
)
from pkuclaw.core.runtime import CoreRuntime
from pkuclaw.config import (
    AgentConfig,
    AppConfig,
    CodexConfig,
    FeishuConfig,
    NotifyQueueConfig,
    Settings,
)
from pkuclaw.core.models import AgentResult, AgentRunRequest, AgentSettings, TaskPlan
from pkuclaw.core.store import Store
from pkuclaw.notify_queue.worker import NotifyQueueWorker
from pkuclaw.runtime.config import (
    SUPPORTED_NOTIFY_POLICIES,
    RuntimeConfigStore,
    describe_notify_policy,
)
from pkuclaw.runtime.events import read_event_catalog, resolve_channel_event_id
from pkuclaw.runtime.prompts import read_prompt_templates, render_prompt_template
from pkuclaw.runtime.skills import (
    OUTBOX_SKILL_NAME,
    load_skill_registry,
    resolve_subskill_names,
)


ROOT = Path(__file__).resolve().parents[1]


def _settings(data_dir: Path, runtime_dir: Path) -> Settings:
    return Settings(
        config_path=ROOT / "configs" / "config.example.toml",
        app=AppConfig(
            name="PkuClawTest",
            data_dir=data_dir,
            runtime_config_dir=runtime_dir,
            timezone="Asia/Shanghai",
        ),
        feishu=FeishuConfig(
            app_id="cli_test",
            app_secret="secret",
            app_secret_env="FEISHU_APP_SECRET",
            event_mode="websocket",
        ),
        agent=AgentConfig(provider="codex"),
        codex=CodexConfig(
            bin="codex",
            sandbox="danger-full-access",
            model="gpt-test",
            timeout_seconds=60,
            max_concurrent_runs=1,
        ),
        notify_queue=NotifyQueueConfig(
            queue_dir=Path("notify_queue"),
            scan_interval_seconds=5,
        ),
    )


def _wrapper(tmp: Path) -> AgentWrapper:
    runtime_config = RuntimeConfigStore(ROOT / "configs" / "runtime")
    return AgentWrapper(
        settings=_settings(tmp / "data", ROOT / "configs" / "runtime"),
        store=Store(
            tmp / "pkuclaw.db",
            default_agent_settings=runtime_config.read_snapshot().agent,
        ),
        runtime_config=runtime_config,
        repo_root=ROOT,
    )


def _core_runtime(wrapper: AgentWrapper) -> CoreRuntime:
    return CoreRuntime(
        store=wrapper.store,
        agent_wrapper=wrapper,
        runtime_config=wrapper.runtime_config,
    )


class PromptArchitectureTests(unittest.TestCase):
    def test_python_package_layout_has_no_legacy_runtime_modules(self) -> None:
        for path in (
            ROOT / "pkuclaw" / "runtime" / "config.py",
            ROOT / "pkuclaw" / "runtime" / "events.py",
            ROOT / "pkuclaw" / "runtime" / "prompts.py",
            ROOT / "pkuclaw" / "runtime" / "skills.py",
            ROOT / "pkuclaw" / "agents" / "providers" / "codex.py",
            ROOT / "pkuclaw" / "core" / "runtime.py",
            ROOT / "pkuclaw" / "core" / "loops.py",
            ROOT / "pkuclaw" / "notify_queue" / "worker.py",
        ):
            self.assertTrue(path.is_file(), str(path))

        for path in (
            ROOT / "pkuclaw" / "runtime_config.py",
            ROOT / "pkuclaw" / "runtime_events.py",
            ROOT / "pkuclaw" / "runtime_prompts.py",
            ROOT / "pkuclaw" / "code_agents",
            ROOT / "pkuclaw" / "connectors" / "pku3b.py",
            ROOT / "pkuclaw" / "notify_http",
        ):
            self.assertFalse(path.exists(), str(path))

    def test_prompt_templates_are_runtime_files_not_wrapper_literals(self) -> None:
        templates = read_prompt_templates(ROOT / "configs" / "runtime")
        self.assertIn("# PkuClaw Realtime Task", templates.realtime.template)
        self.assertIn("# PkuClaw Loop Task", templates.loop.template)
        self.assertIn("## Suggested Skills", templates.realtime.suggested_skills_template)

        rendered = render_prompt_template(
            templates.realtime.template,
            {
                "skill_catalog": "- none",
                "suggested_skills_section": "",
                "user_request": "你好",
            },
        )
        self.assertIn("## User Request", rendered)
        self.assertIn("你好", rendered)

        wrapper_source = (ROOT / "pkuclaw" / "agents" / "wrapper.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("你是 PkuClaw 的实时学习/课程助手", wrapper_source)
        self.assertNotIn("你正在执行 PkuClaw 的后台周期任务", wrapper_source)
        self.assertNotIn("## Suggested Skills", wrapper_source)

    def test_realtime_prompt_is_minimal_and_has_no_outbox_script_body(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            wrapper = _wrapper(Path(raw_tmp))
            request = AgentRunRequest(
                source="realtime",
                conversation_id="chat-1",
                text="这周有什么作业？",
                suggested_skills=(),
            )
            plan = TaskPlan(suggested_skills=(), ack="ok")
            prepared = wrapper.prepare(request, plan)
            context = wrapper._build_context(  # noqa: SLF001 - prompt contract test
                run=wrapper.store.get_run(prepared.run_id),
                request=request,
                plan=plan,
            )
            prompt = wrapper.build_run_prompt(context)

        self.assertIn("# PkuClaw Realtime Task", prompt)
        self.assertIn("## Skill Catalog", prompt)
        self.assertIn("## User Request", prompt)
        self.assertIn("configs/runtime/skills/tools/channel-outbox.md", prompt)
        self.assertIn("不要在用户未要求时额外发送 text", prompt)
        self.assertNotIn("# PkuClaw Loop Task", prompt)
        self.assertNotIn("## Channel Outbox Skill", prompt)
        self.assertNotIn("channel_send_text", prompt)
        self.assertNotIn("pkuclaw_outbox.py", prompt)
        self.assertNotIn("pkuclaw_outbox_legacy.py", prompt)
        self.assertNotIn("runtime_get_status", prompt)
        self.assertNotIn("Run ID", prompt)
        self.assertNotIn("Agent Settings", prompt)
        self.assertNotIn("Repository root", prompt)
        self.assertNotIn(str(ROOT), prompt)
        self.assertNotIn("Recent Runs", prompt)
        self.assertNotIn("## PkuClaw Skills", prompt)
        self.assertNotIn("## Suggested Skills", prompt)
        self.assertNotIn("# 任务：同步课程通知", prompt)

    def test_loop_prompt_points_to_channel_outbox_skill(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            wrapper = _wrapper(Path(raw_tmp))
            request = AgentRunRequest(
                source="loop",
                conversation_id="daemon:loop:sync_notices",
                text="检查课程状态。",
                suggested_skills=("tasks/sync-notices.md",),
                sink_mode="silent",
                channel_context={
                    "loop_id": "sync_notices",
                    "scheduled_at": "2026-05-07T00:00:00+00:00",
                    "target": {
                        "channel": "feishu",
                        "target_type": "chat_id",
                        "target_id": "oc_test",
                    },
                },
            )
            plan = TaskPlan(suggested_skills=request.suggested_skills, ack="ok")
            prepared = wrapper.prepare(request, plan)
            context = wrapper._build_context(  # noqa: SLF001 - prompt contract test
                run=wrapper.store.get_run(prepared.run_id),
                request=request,
                plan=plan,
            )
            prompt = wrapper.build_run_prompt(context)

        self.assertIn("# PkuClaw Loop Task", prompt)
        self.assertIn("## Notification Policy", prompt)
        self.assertIn("只在重要变化或需要用户处理时通知", prompt)
        self.assertEqual(prompt.count("只在重要变化或需要用户处理时通知"), 1)
        self.assertIn("## Channel Outbox Skill", prompt)
        self.assertIn(OUTBOX_SKILL_NAME, prompt)
        self.assertNotIn("channel_send_text", prompt)
        self.assertNotIn("# PkuClaw Realtime Task", prompt)
        self.assertNotIn("runtime_get_config", prompt)
        self.assertNotIn("runtime_add_loop", prompt)
        self.assertNotIn("Agent Settings", prompt)
        self.assertNotIn("# 任务：同步课程通知", prompt)
        self.assertIn("configs/runtime/skills/tasks/sync-notices.md", prompt)

    def test_notify_policy_descriptions_are_available_to_loop_prompts(self) -> None:
        self.assertEqual(
            set(SUPPORTED_NOTIFY_POLICIES),
            {"important_only", "always", "silent", "on_error", "digest"},
        )
        for policy in SUPPORTED_NOTIFY_POLICIES:
            description = describe_notify_policy(policy)
            self.assertTrue(description)
        self.assertNotIn("MCP", describe_notify_policy("always"))


class CodexCommandConfigTests(unittest.TestCase):
    def test_codex_command_uses_full_access_bypass_without_approval_config(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            settings = _settings(Path(raw_tmp) / "data", ROOT / "configs" / "runtime")
            agent = CodexAgent(settings=settings, repo_root=ROOT)
            runtime = RuntimeConfigStore(ROOT / "configs" / "runtime").read_snapshot()
            command = agent._build_command(  # noqa: SLF001 - command contract test
                session_id=None,
                result_path=Path(raw_tmp) / "result.md",
                agent_settings=AgentSettings(),
                runtime=runtime,
            )
            resume_command = agent._build_command(  # noqa: SLF001 - command contract test
                session_id="session-test",
                result_path=Path(raw_tmp) / "result.md",
                agent_settings=AgentSettings(),
                runtime=runtime,
            )

        command_text = "\n".join(command)
        resume_command_text = "\n".join(resume_command)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", resume_command)
        self.assertNotIn("-s", command)
        self.assertNotIn("-s", resume_command)
        self.assertNotIn("approval_policy", command_text)
        self.assertNotIn("approval_policy", resume_command_text)
        self.assertNotIn("approvals_reviewer", command_text)
        self.assertNotIn("approvals_reviewer", resume_command_text)
        self.assertNotIn("default_tools_approval_mode", command_text)
        self.assertNotIn("mcp_servers", command_text)
        self.assertNotIn("mcp_servers", resume_command_text)
        self.assertNotIn("pkuclaw_daemon", command_text)
        self.assertNotIn("pkuclaw_daemon", resume_command_text)


class SkillCatalogTests(unittest.TestCase):
    def test_empty_skill_request_does_not_inject_base_skill(self) -> None:
        registry = load_skill_registry(
            ROOT / "configs" / "runtime" / "skills.json",
            skills_dir=ROOT / "configs" / "runtime" / "skills",
        )
        self.assertEqual(
            resolve_subskill_names(
                (),
                registry=registry,
                skills_dir=ROOT / "configs" / "runtime" / "skills",
                source="realtime",
            ),
            (),
        )

    def test_broken_skill_catalog_returns_warning_and_empty_registry(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            skills_dir = tmp / "skills"
            skills_dir.mkdir()
            broken = tmp / "skills.json"
            broken.write_text("{bad json", encoding="utf-8")
            registry = load_skill_registry(broken, skills_dir=skills_dir)

        self.assertEqual(list(registry.skills), [])
        self.assertTrue(registry.warnings)
        self.assertIn("skill registry unavailable", registry.warnings[0])

    def test_skills_json_contains_runtime_paths_not_legacy_fields(self) -> None:
        data = json.loads((ROOT / "configs" / "runtime" / "skills.json").read_text())
        for item in data["skills"]:
            self.assertIn("path", item)
            self.assertNotIn("intent", item)
            self.assertTrue((ROOT / "configs" / "runtime" / "skills" / item["path"]).is_file())


class RuntimeConfigTests(unittest.TestCase):
    def test_notify_policy_is_validated_as_global_notification_config(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            (tmp / "runtime.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "notifications": {
                            "policy": "on_error",
                            "default_channel": "feishu",
                            "default_target_type": "open_id",
                            "default_target_id": "ou-owner",
                        },
                        "loops": [
                            {
                                "id": "errors_only",
                                "enabled": True,
                                "prompt": "check",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            runtime = RuntimeConfigStore(tmp).read_snapshot()

        self.assertEqual(runtime.notifications.policy, "on_error")
        self.assertEqual(runtime.notifications.default_channel, "feishu")
        self.assertEqual(runtime.notifications.default_target_type, "open_id")
        self.assertEqual(runtime.notifications.default_target_id, "ou-owner")
        self.assertIsNone(runtime.loops[0].default_target_id)

    def test_loop_dispatch_uses_global_target_and_allows_loop_override(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            runtime_dir = tmp / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "runtime.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "notifications": {
                            "policy": "important_only",
                            "default_channel": "feishu",
                            "default_target_type": "open_id",
                            "default_target_id": "ou-owner",
                        },
                        "loops": [
                            {
                                "id": "inherits_global",
                                "enabled": True,
                                "prompt": "check",
                            },
                            {
                                "id": "overrides_target",
                                "enabled": True,
                                "prompt": "check",
                                "default_channel": "feishu",
                                "default_target_type": "chat_id",
                                "default_target_id": "oc-loop",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            wrapper = AgentWrapper(
                settings=_settings(tmp / "data", runtime_dir),
                store=Store(tmp / "pkuclaw.db"),
                runtime_config=RuntimeConfigStore(runtime_dir),
                repo_root=ROOT,
            )
            core_runtime = _core_runtime(wrapper)
            inherited = core_runtime.create_loop_run(loop_id="inherits_global")
            overridden = core_runtime.create_loop_run(loop_id="overrides_target")

        self.assertEqual(
            inherited.agent_request.channel_context["target"],
            {
                "channel": "feishu",
                "target_type": "open_id",
                "target_id": "ou-owner",
            },
        )
        self.assertEqual(inherited.agent_request.channel, "feishu")
        self.assertIn(OUTBOX_SKILL_NAME, inherited.agent_request.suggested_skills)
        self.assertEqual(
            overridden.agent_request.channel_context["target"],
            {
                "channel": "feishu",
                "target_type": "chat_id",
                "target_id": "oc-loop",
            },
        )
        self.assertEqual(overridden.agent_request.channel, "feishu")


class StoreModelTests(unittest.TestCase):
    def test_new_conversation_persists_default_agent_settings(self) -> None:
        defaults = AgentSettings(
            provider="codex",
            mode="fixed",
            model="gpt-db-default",
            reasoning_effort="high",
        )
        with tempfile.TemporaryDirectory() as raw_tmp:
            db_path = Path(raw_tmp) / "pkuclaw.db"
            store = Store(db_path, default_agent_settings=defaults)
            conversation = store.ensure_conversation("chat-1")

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            columns = {
                row["name"]: row["notnull"]
                for row in conn.execute("pragma table_info(conversations)")
            }
            run_columns = {
                row["name"]
                for row in conn.execute("pragma table_info(runs)")
            }

        self.assertEqual(conversation.agent_settings, defaults)
        self.assertEqual(columns["agent_provider"], 1)
        self.assertEqual(columns["agent_mode"], 1)
        self.assertEqual(columns["agent_model"], 1)
        self.assertEqual(columns["agent_reasoning_effort"], 1)
        self.assertNotIn("prompt_path", run_columns)
        self.assertNotIn("stdout_path", run_columns)
        self.assertNotIn("stderr_path", run_columns)

    def test_run_metadata_records_structured_runtime_facts(self) -> None:
        class NullSink:
            def emit(self, event: object) -> None:
                return None

        class FakeAgent:
            name = "codex"

            def execute(self, context: object, prompt: str, sink: object) -> AgentResult:
                paths = context.paths  # type: ignore[attr-defined]
                paths.stdout_path.write_text(
                    json.dumps({"type": "turn.completed"}) + "\n",
                    encoding="utf-8",
                )
                paths.result_path.write_text("完成", encoding="utf-8")
                return AgentResult(
                    run_id=context.run.run_id,  # type: ignore[attr-defined]
                    status="succeeded",
                    response_text="完成",
                    session_id="session-1",
                    result_path=paths.result_path,
                )

        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            wrapper = _wrapper(tmp)
            wrapper._codex = FakeAgent()  # noqa: SLF001 - inject fake provider
            request = AgentRunRequest(
                source="realtime",
                conversation_id="chat-structured",
                text="你好",
                suggested_skills=(),
                channel="feishu",
                sender_id="ou-user",
                channel_context={
                    "target": {
                        "channel": "feishu",
                        "target_type": "open_id",
                        "target_id": "ou-user",
                    }
                },
            )
            plan = TaskPlan(suggested_skills=(), ack="ok")
            prepared = wrapper.prepare(request, plan)
            wrapper.run(
                run_id=prepared.run_id,
                request=request,
                plan=plan,
                sink=NullSink(),
            )
            metadata = wrapper.store.get_run_metadata(prepared.run_id)
            detail = wrapper.store.get_run_detail(prepared.run_id)
            card_detail = build_codex_artifact_detail(
                store=wrapper.store,
                run_id=prepared.run_id,
            )

        self.assertEqual(metadata["source"], "realtime")
        self.assertEqual(metadata["loop"], None)
        self.assertEqual(metadata["channel"]["name"], "feishu")
        self.assertEqual(metadata["channel"]["sender_id"], "ou-user")
        self.assertIn("agent", metadata)
        self.assertIn("paths", metadata)
        self.assertNotIn("provider", metadata)
        self.assertNotIn("model", metadata)
        self.assertNotIn("run_dir", metadata)
        self.assertEqual(detail.agent.model, "gpt-5.5")
        self.assertTrue(detail.paths["stdout"].endswith("stdout.jsonl"))
        self.assertEqual(card_detail.agent_context["model"], "gpt-5.5")
        self.assertIn("回合完成", "\n".join(card_detail.events))

    def test_loop_run_metadata_uses_structured_loop_and_channel_objects(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            runtime_dir = tmp / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "runtime.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "notifications": {
                            "policy": "always",
                            "default_channel": "feishu",
                            "default_target_type": "chat_id",
                            "default_target_id": "oc-loop",
                        },
                        "loops": [
                            {
                                "id": "structured_loop",
                                "enabled": True,
                                "prompt": "check",
                                "sink_mode": "silent",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            runtime_config = RuntimeConfigStore(runtime_dir)
            wrapper = AgentWrapper(
                settings=_settings(tmp / "data", runtime_dir),
                store=Store(
                    tmp / "pkuclaw.db",
                    default_agent_settings=runtime_config.read_snapshot().agent,
                ),
                runtime_config=runtime_config,
                repo_root=ROOT,
            )
            dispatch = _core_runtime(wrapper).create_loop_run(
                loop_id="structured_loop",
                scheduled_at="2026-05-07T00:00:00+00:00",
            )
            metadata = wrapper.store.get_run_metadata(str(dispatch.run_id))

        self.assertEqual(metadata["source"], "loop")
        self.assertEqual(metadata["loop"]["id"], "structured_loop")
        self.assertEqual(metadata["loop"]["notify_policy"], "always")
        self.assertEqual(metadata["loop"]["scheduled_at"], "2026-05-07T00:00:00+00:00")
        self.assertEqual(metadata["channel"]["name"], "feishu")
        self.assertEqual(metadata["channel"]["target"]["target_id"], "oc-loop")
        self.assertNotIn("loop_id", metadata)
        self.assertNotIn("target", metadata)

    def test_failed_run_keeps_error_response_and_result_path_for_detail(self) -> None:
        class NullSink:
            def emit(self, event: object) -> None:
                return None

        class FailingAgent:
            name = "codex"

            def execute(self, context: object, prompt: str, sink: object) -> AgentResult:
                paths = context.paths  # type: ignore[attr-defined]
                paths.stdout_path.write_text(
                    json.dumps({"type": "item.failed"}) + "\n",
                    encoding="utf-8",
                )
                paths.result_path.write_text("失败摘要", encoding="utf-8")
                return AgentResult(
                    run_id=context.run.run_id,  # type: ignore[attr-defined]
                    status="failed",
                    response_text="失败摘要",
                    session_id=None,
                    result_path=paths.result_path,
                    error="执行失败",
                )

        with tempfile.TemporaryDirectory() as raw_tmp:
            wrapper = _wrapper(Path(raw_tmp))
            wrapper._codex = FailingAgent()  # noqa: SLF001 - inject fake provider
            request = AgentRunRequest(
                source="realtime",
                conversation_id="chat-failed",
                text="失败测试",
                suggested_skills=(),
            )
            plan = TaskPlan(suggested_skills=(), ack="ok")
            prepared = wrapper.prepare(request, plan)
            wrapper.run(
                run_id=prepared.run_id,
                request=request,
                plan=plan,
                sink=NullSink(),
            )
            wrapper.store.mark_run_failed(prepared.run_id, "outer handler failed")
            run = wrapper.store.get_run(prepared.run_id)
            detail = build_codex_artifact_detail(
                store=wrapper.store,
                run_id=prepared.run_id,
            )

        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error, "outer handler failed")
        self.assertEqual(run.response_text, "失败摘要")
        self.assertIsNotNone(run.result_path)
        self.assertIn("步骤失败", "\n".join(detail.events))


class RuntimeEventTests(unittest.TestCase):
    def test_runtime_event_id_creates_streaming_realtime_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            wrapper = _wrapper(Path(raw_tmp))
            core_runtime = _core_runtime(wrapper)
            dispatch = core_runtime.ingest_channel_message(
                ChannelInboundMessage(
                    channel="feishu",
                    conversation_id="feishu:user:ou-test",
                    sender_id="ou-test",
                    target=ChannelTarget(
                        channel="feishu",
                        target_type="open_id",
                        target_id="ou-test",
                    ),
                    text="",
                    event_id="course_updates",
                )
            )

            self.assertIsNotNone(dispatch.run_id)
            self.assertIsNotNone(dispatch.agent_request)
            self.assertEqual(dispatch.agent_request.source, "realtime")
            self.assertIn("教学网更新", dispatch.agent_request.text)
            self.assertEqual(dispatch.agent_request.suggested_skills, ("tasks/sync-notices.md",))
            self.assertEqual(dispatch.reply_text, "正在查看教学网更新。")
            context = wrapper._build_context(  # noqa: SLF001 - prompt contract test
                run=wrapper.store.get_run(str(dispatch.run_id)),
                request=dispatch.agent_request,
                plan=dispatch.plan,
            )
            prompt = wrapper.build_run_prompt(context)
            self.assertIn("## Suggested Skills", prompt)
            self.assertIn("configs/runtime/skills/tasks/sync-notices.md", prompt)

    def test_runtime_event_catalog_supports_direct_channel_passthrough(self) -> None:
        catalog = read_event_catalog(ROOT / "configs" / "runtime")
        self.assertEqual(
            catalog.resolve_channel_event_id(channel="feishu", raw_event_id="course_updates"),
            "course_updates",
        )
        self.assertIsNone(
            resolve_channel_event_id(
                config_dir=ROOT / "configs" / "runtime",
                channel="feishu",
                raw_event_id="unknown_feishu_menu",
            )
        )

    def test_events_json_contains_quick_action_tasks(self) -> None:
        data = json.loads((ROOT / "configs" / "runtime" / "events.json").read_text())
        self.assertIn("events", data)
        for item in data["events"]:
            self.assertIn("id", item)
            self.assertIn("task", item)
            self.assertIn("skill_names", item)



class NotifyQueueTests(unittest.TestCase):
    def test_outbox_text_uses_loop_override_target_and_title(self) -> None:
        class RecordingBackend:
            channel = "feishu"

            def __init__(self) -> None:
                self.last_text: tuple[ChannelTarget, str, str | None] | None = None

            def send_text(
                self,
                *,
                target: ChannelTarget,
                text: str,
                title: str | None = None,
            ) -> ChannelOutboundResult:
                self.last_text = (target, text, title)
                return ChannelOutboundResult(ok=True, message="text sent", target=target)

            def send_card(self, *, target: ChannelTarget, card: dict) -> ChannelOutboundResult:
                return ChannelOutboundResult(ok=True, message="card sent", target=target)

            def send_image(
                self,
                *,
                target: ChannelTarget,
                image_path: str,
                caption: str | None = None,
            ) -> ChannelOutboundResult:
                return ChannelOutboundResult(ok=True, message="image sent", target=target)

            def send_file(
                self,
                *,
                target: ChannelTarget,
                file_path: str,
                caption: str | None = None,
            ) -> ChannelOutboundResult:
                return ChannelOutboundResult(ok=True, message="file sent", target=target)

            def update_card(
                self,
                *,
                card_id: str,
                card: dict,
                sequence: int,
            ) -> ChannelOutboundResult:
                return ChannelOutboundResult(ok=True, message="card updated")

        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            runtime_dir = tmp / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "runtime.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "notifications": {
                            "policy": "important_only",
                            "default_channel": "feishu",
                            "default_target_type": "open_id",
                            "default_target_id": "ou-owner",
                        },
                        "loops": [
                            {
                                "id": "overrides_target",
                                "enabled": True,
                                "prompt": "check",
                                "default_channel": "feishu",
                                "default_target_type": "chat_id",
                                "default_target_id": "oc-loop",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            wrapper = AgentWrapper(
                settings=_settings(tmp / "data", runtime_dir),
                store=Store(tmp / "pkuclaw.db"),
                runtime_config=RuntimeConfigStore(runtime_dir),
                repo_root=ROOT,
            )
            core_runtime = _core_runtime(wrapper)
            backend = RecordingBackend()
            core_runtime.register_channel_backend(backend)
            worker = NotifyQueueWorker(
                queue_dir=tmp / "notify_queue",
                scan_interval_seconds=5,
                core_runtime=core_runtime,
            )
            pending = worker.pending_dir
            pending.mkdir(parents=True)
            (pending / "job-1.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "job_id": "job-1",
                        "kind": "text",
                        "loop_id": "overrides_target",
                        "payload": {"text": "覆盖成功", "title": "课程提醒"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            processed = worker.process_pending()
            ack = json.loads((worker.ack_dir / "job-1.json").read_text(encoding="utf-8"))

        self.assertEqual(processed, 1)
        self.assertTrue(ack["ok"])
        self.assertEqual(ack["target"]["target_type"], "chat_id")
        self.assertEqual(ack["target"]["target_id"], "oc-loop")
        self.assertIsNotNone(backend.last_text)
        target, text, title = backend.last_text
        self.assertEqual(text, "覆盖成功")
        self.assertEqual(title, "课程提醒")
        self.assertEqual(target.channel, "feishu")
        self.assertEqual(target.target_type, "chat_id")
        self.assertEqual(target.target_id, "oc-loop")

    def test_outbox_image_and_file_use_realtime_run_target(self) -> None:
        class RecordingBackend:
            channel = "feishu"

            def __init__(self) -> None:
                self.images: list[tuple[ChannelTarget, str, str | None]] = []
                self.files: list[tuple[ChannelTarget, str, str | None]] = []

            def send_text(
                self,
                *,
                target: ChannelTarget,
                text: str,
                title: str | None = None,
            ) -> ChannelOutboundResult:
                return ChannelOutboundResult(ok=True, message="text sent", target=target)

            def send_card(self, *, target: ChannelTarget, card: dict) -> ChannelOutboundResult:
                return ChannelOutboundResult(ok=True, message="card sent", target=target)

            def send_image(
                self,
                *,
                target: ChannelTarget,
                image_path: str,
                caption: str | None = None,
            ) -> ChannelOutboundResult:
                self.images.append((target, image_path, caption))
                return ChannelOutboundResult(
                    ok=True,
                    message="image sent",
                    target=target,
                    external_message_id="msg-image",
                    data={"image_path": image_path},
                )

            def send_file(
                self,
                *,
                target: ChannelTarget,
                file_path: str,
                caption: str | None = None,
            ) -> ChannelOutboundResult:
                self.files.append((target, file_path, caption))
                return ChannelOutboundResult(
                    ok=True,
                    message="file sent",
                    target=target,
                    external_message_id="msg-file",
                    data={"file_path": file_path},
                )

            def update_card(
                self,
                *,
                card_id: str,
                card: dict,
                sequence: int,
            ) -> ChannelOutboundResult:
                return ChannelOutboundResult(ok=True, message="card updated")

        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            wrapper = _wrapper(tmp)
            request = AgentRunRequest(
                source="realtime",
                conversation_id="chat-media",
                text="生成图和 PDF",
                suggested_skills=(),
                channel="feishu",
                sender_id="ou-user",
                channel_context={
                    "target": {
                        "channel": "feishu",
                        "target_type": "open_id",
                        "target_id": "ou-user",
                    }
                },
            )
            prepared = wrapper.prepare(request, TaskPlan(suggested_skills=(), ack="ok"))
            core_runtime = _core_runtime(wrapper)
            backend = RecordingBackend()
            core_runtime.register_channel_backend(backend)
            worker = NotifyQueueWorker(
                queue_dir=tmp / "notify_queue",
                scan_interval_seconds=5,
                core_runtime=core_runtime,
            )
            pending = worker.pending_dir
            pending.mkdir(parents=True)
            (pending / "image.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "job_id": "image",
                        "kind": "image",
                        "run_id": prepared.run_id,
                        "run_source": "realtime",
                        "payload": {"path": "/tmp/image.png", "caption": "结果图"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (pending / "file.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "job_id": "file",
                        "kind": "file",
                        "run_id": prepared.run_id,
                        "run_source": "realtime",
                        "payload": {"path": "/tmp/result.pdf", "caption": "完整 PDF"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            processed = worker.process_pending()
            image_ack = json.loads((worker.ack_dir / "image.json").read_text())
            file_ack = json.loads((worker.ack_dir / "file.json").read_text())

        self.assertEqual(processed, 2)
        self.assertTrue(image_ack["ok"])
        self.assertTrue(file_ack["ok"])
        self.assertEqual(image_ack["target"]["target_id"], "ou-user")
        self.assertEqual(file_ack["target"]["target_id"], "ou-user")
        self.assertEqual(backend.images[0][1:], ("/tmp/image.png", "结果图"))
        self.assertEqual(backend.files[0][1:], ("/tmp/result.pdf", "完整 PDF"))

    def test_outbox_rejects_card_update_and_missing_default_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            runtime_dir = tmp / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "runtime.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "notifications": {"policy": "important_only"},
                        "loops": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            wrapper = AgentWrapper(
                settings=_settings(tmp / "data", runtime_dir),
                store=Store(tmp / "pkuclaw.db"),
                runtime_config=RuntimeConfigStore(runtime_dir),
                repo_root=ROOT,
            )
            worker = NotifyQueueWorker(
                queue_dir=tmp / "notify_queue",
                scan_interval_seconds=5,
                core_runtime=_core_runtime(wrapper),
            )
            pending = worker.pending_dir
            pending.mkdir(parents=True)
            (pending / "card.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "job_id": "card",
                        "kind": "card_update",
                        "payload": {"card_id": "card-1"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (pending / "missing.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "job_id": "missing",
                        "kind": "text",
                        "payload": {"text": "测试成功"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            processed = worker.process_pending()
            card_ack = json.loads((worker.ack_dir / "card.json").read_text())
            missing_ack = json.loads((worker.ack_dir / "missing.json").read_text())

        self.assertEqual(processed, 2)
        self.assertFalse(card_ack["ok"])
        self.assertIn("unsupported outbox job kind", card_ack["message"])
        self.assertFalse(missing_ack["ok"])
        self.assertIn("no outbox target configured", missing_ack["message"])

    def test_outbox_script_enqueues_random_file_with_run_env(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            queue_dir = Path(raw_tmp) / "notify_queue"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "pkuclaw_outbox.py"),
                    "--no-wait",
                    "text",
                    "--text",
                    "测试成功",
                    "--title",
                    "课程提醒",
                ],
                cwd=ROOT,
                env={
                    "PATH": "",
                    "PKUCLAW_OUTBOX_QUEUE_DIR": str(queue_dir),
                    "PKUCLAW_RUN_ID": "run-test",
                    "PKUCLAW_RUN_SOURCE": "loop",
                    "PKUCLAW_LOOP_ID": "test_loop",
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            payload = json.loads(completed.stdout)
            pending_files = list((queue_dir / "pending").glob("*.json"))
            job = json.loads(pending_files[0].read_text(encoding="utf-8"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["message"], "queued")
        self.assertEqual(len(pending_files), 1)
        self.assertEqual(job["schema_version"], 2)
        self.assertEqual(job["kind"], "text")
        self.assertEqual(job["run_id"], "run-test")
        self.assertEqual(job["run_source"], "loop")
        self.assertEqual(job["loop_id"], "test_loop")
        self.assertEqual(job["payload"], {"text": "测试成功", "title": "课程提醒"})
        self.assertEqual(job["job_id"], payload["data"]["job_id"])


if __name__ == "__main__":
    unittest.main()
