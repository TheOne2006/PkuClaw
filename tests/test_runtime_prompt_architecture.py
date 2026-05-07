from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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
    McpConfig,
    Settings,
)
from pkuclaw.core.models import AgentRunRequest, AgentSettings, TaskPlan
from pkuclaw.core.store import Store
from pkuclaw.mcp.schemas import list_tool_schemas, render_tool_prompt
from pkuclaw.mcp.handlers import DaemonMcpToolHandler
from pkuclaw.runtime.config import (
    SUPPORTED_NOTIFY_POLICIES,
    RuntimeConfigStore,
    describe_notify_policy,
)
from pkuclaw.runtime.events import read_event_catalog, resolve_channel_event_id
from pkuclaw.runtime.prompts import read_prompt_templates, render_prompt_template
from pkuclaw.runtime.skills import load_skill_registry, resolve_subskill_names


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
            sandbox="workspace-write",
            model="gpt-test",
            timeout_seconds=60,
            max_concurrent_runs=1,
        ),
        mcp=McpConfig(host="127.0.0.1", port=8765),
    )


def _wrapper(tmp: Path) -> AgentWrapper:
    return AgentWrapper(
        settings=_settings(tmp / "data", ROOT / "configs" / "runtime"),
        store=Store(tmp / "pkuclaw.db"),
        runtime_config=RuntimeConfigStore(ROOT / "configs" / "runtime"),
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
        ):
            self.assertTrue(path.is_file(), str(path))

        for path in (
            ROOT / "pkuclaw" / "runtime_config.py",
            ROOT / "pkuclaw" / "runtime_events.py",
            ROOT / "pkuclaw" / "runtime_prompts.py",
            ROOT / "pkuclaw" / "code_agents",
            ROOT / "pkuclaw" / "connectors" / "pku3b.py",
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

    def test_realtime_prompt_is_minimal_and_has_no_mcp_tools(self) -> None:
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
        self.assertNotIn("# PkuClaw Loop Task", prompt)
        self.assertNotIn("## Channel Notification Tools", prompt)
        self.assertNotIn("channel_send_text", prompt)
        self.assertNotIn("runtime_get_status", prompt)
        self.assertNotIn("Run ID", prompt)
        self.assertNotIn("Agent Settings", prompt)
        self.assertNotIn("Repository root", prompt)
        self.assertNotIn(str(ROOT), prompt)
        self.assertNotIn("Recent Runs", prompt)
        self.assertNotIn("## PkuClaw Skills", prompt)
        self.assertNotIn("## Suggested Skills", prompt)
        self.assertNotIn("# 任务：同步课程通知", prompt)

    def test_loop_prompt_only_lists_channel_notification_tools(self) -> None:
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
        self.assertIn("每次 loop 完成都发送简洁通知", prompt)
        self.assertEqual(prompt.count("每次 loop 完成都发送简洁通知"), 1)
        self.assertIn("## Channel Notification Tools", prompt)
        for name in (
            "channel_send_text",
            "channel_send_card",
            "channel_send_image",
            "channel_update_card",
        ):
            self.assertIn(name, prompt)
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
        tool_prompt = render_tool_prompt()
        self.assertIn("configured default notification target", tool_prompt)
        self.assertNotIn("每次 loop 完成都发送简洁通知", tool_prompt)
        self.assertNotIn("Active notification policy", tool_prompt)


class CodexCommandConfigTests(unittest.TestCase):
    def test_loop_mcp_tool_approval_mode_uses_server_scoped_auto(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            settings = _settings(Path(raw_tmp) / "data", ROOT / "configs" / "runtime")
            agent = CodexAgent(settings=settings, repo_root=ROOT)
            runtime = RuntimeConfigStore(ROOT / "configs" / "runtime").read_snapshot()
            command = agent._build_command(  # noqa: SLF001 - command contract test
                session_id=None,
                result_path=Path(raw_tmp) / "result.md",
                agent_settings=AgentSettings(),
                runtime=runtime,
                enable_mcp=True,
            )
            loop_command = agent._build_command(  # noqa: SLF001 - command contract test
                session_id=None,
                result_path=Path(raw_tmp) / "result.md",
                agent_settings=AgentSettings(),
                runtime=runtime,
                enable_mcp=True,
                mcp_loop_id="test_loop",
            )

        command_text = "\n".join(command)
        self.assertIn('approvals_reviewer="auto_review"', command)
        self.assertIn(
            'mcp_servers.pkuclaw_daemon.default_tools_approval_mode="auto"',
            command,
        )
        self.assertNotIn('default_tools_approval_mode="auto_review"', command_text)
        self.assertIn(
            'mcp_servers.pkuclaw_daemon.url="http://127.0.0.1:8765/mcp?loop_id=test_loop"',
            loop_command,
        )


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
        self.assertEqual(
            overridden.agent_request.channel_context["target"],
            {
                "channel": "feishu",
                "target_type": "chat_id",
                "target_id": "oc-loop",
            },
        )
        self.assertEqual(overridden.agent_request.channel, "feishu")


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


class McpToolSchemaTests(unittest.TestCase):
    def test_mcp_registry_exposes_only_channel_tools(self) -> None:
        names = {tool["name"] for tool in list_tool_schemas()}
        self.assertEqual(
            names,
            {
                "channel_send_text",
                "channel_send_card",
                "channel_send_image",
                "channel_update_card",
            },
        )
        prompt = render_tool_prompt()
        self.assertIn("channel_send_text", prompt)
        self.assertIn("configured default notification target", prompt)
        self.assertNotIn("target_id", prompt)
        self.assertNotIn("runtime_get_status", prompt)
        self.assertNotIn("runtime_update_loop", prompt)

    def test_send_tools_use_fixed_default_target_schema(self) -> None:
        tools = {tool["name"]: tool["inputSchema"] for tool in list_tool_schemas()}
        self.assertEqual(tools["channel_send_text"]["required"], ["text"])
        self.assertEqual(set(tools["channel_send_text"]["properties"]), {"text"})
        self.assertFalse(tools["channel_send_text"]["additionalProperties"])
        self.assertEqual(tools["channel_send_card"]["required"], ["card"])
        self.assertEqual(set(tools["channel_send_card"]["properties"]), {"card"})
        self.assertFalse(tools["channel_send_card"]["additionalProperties"])
        self.assertEqual(tools["channel_send_image"]["required"], ["image_path"])
        self.assertEqual(
            set(tools["channel_send_image"]["properties"]),
            {"image_path"},
        )
        self.assertFalse(tools["channel_send_image"]["additionalProperties"])

    def test_mcp_send_text_uses_resolved_config_target(self) -> None:
        class RecordingBackend:
            channel = "feishu"

            def __init__(self) -> None:
                self.last_text: tuple[ChannelTarget, str] | None = None

            def send_text(
                self,
                *,
                target: ChannelTarget,
                text: str,
            ) -> ChannelOutboundResult:
                self.last_text = (target, text)
                return ChannelOutboundResult(
                    ok=True,
                    message="text sent",
                    target=target,
                    data={},
                )

            def send_card(
                self,
                *,
                target: ChannelTarget,
                card: dict,
            ) -> ChannelOutboundResult:
                return ChannelOutboundResult(ok=True, message="card sent", target=target)

            def send_image(
                self,
                *,
                target: ChannelTarget,
                image_path: str,
            ) -> ChannelOutboundResult:
                return ChannelOutboundResult(ok=True, message="image sent", target=target)

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
            handler = DaemonMcpToolHandler(core_runtime=core_runtime)

            result = handler.call_tool("channel_send_text", {"text": "测试成功"})
            override_result = handler.call_tool(
                "channel_send_text",
                {"text": "覆盖成功"},
                loop_id="overrides_target",
            )

        self.assertTrue(result.ok)
        self.assertTrue(override_result.ok)
        self.assertEqual(result.data["target"]["target_type"], "open_id")
        self.assertEqual(result.data["target"]["target_id"], "ou-owner")
        self.assertIsNotNone(backend.last_text)
        target, text = backend.last_text
        self.assertEqual(text, "覆盖成功")
        self.assertEqual(target.channel, "feishu")
        self.assertEqual(target.target_type, "chat_id")
        self.assertEqual(target.target_id, "oc-loop")

    def test_mcp_send_text_rejects_legacy_target_arguments(self) -> None:
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
            handler = DaemonMcpToolHandler(core_runtime=_core_runtime(wrapper))

            with self.assertRaisesRegex(RuntimeError, "unsupported arguments"):
                handler.call_tool(
                    "channel_send_text",
                    {"text": "测试成功", "target_id": "legacy"},
                )


if __name__ == "__main__":
    unittest.main()
