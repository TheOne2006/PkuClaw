from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pkuclaw.agents.wrapper import AgentWrapper
from pkuclaw.config import (
    AgentConfig,
    AppConfig,
    CodexConfig,
    FeishuConfig,
    McpConfig,
    MonitorConfig,
    Settings,
)
from pkuclaw.core.models import AgentRunRequest, TaskPlan
from pkuclaw.core.store import Store
from pkuclaw.mcp.schemas import list_tool_schemas, render_tool_prompt
from pkuclaw.runtime_config import RuntimeConfigStore
from pkuclaw.code_agents.subskills import load_skill_registry, resolve_subskill_names


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
        monitor=MonitorConfig(
            scan_interval_seconds=60,
            enable_assignments=True,
            enable_announcements=True,
            enable_replays=True,
            enable_grades=False,
        ),
        mcp=McpConfig(host="127.0.0.1", port=8765),
    )


class PromptArchitectureTests(unittest.TestCase):
    def _wrapper(self, tmp: Path) -> AgentWrapper:
        return AgentWrapper(
            settings=_settings(tmp / "data", ROOT / "configs" / "runtime"),
            store=Store(tmp / "pkuclaw.db"),
            runtime_config=RuntimeConfigStore(ROOT / "configs" / "runtime"),
            repo_root=ROOT,
        )

    def test_realtime_prompt_is_minimal_and_has_no_mcp_tools(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            wrapper = self._wrapper(Path(raw_tmp))
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
        self.assertNotIn("# 任务：同步课程通知", prompt)

    def test_loop_prompt_only_lists_channel_notification_tools(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            wrapper = self._wrapper(Path(raw_tmp))
            request = AgentRunRequest(
                source="loop",
                conversation_id="daemon:loop:sync_notices",
                text="检查课程状态。",
                suggested_skills=("tasks/sync-notices.md",),
                sink_mode="silent",
                channel_context={
                    "loop_id": "sync_notices",
                    "scheduled_at": "2026-05-07T00:00:00+00:00",
                    "notify_policy": "important_only",
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
        self.assertNotIn("runtime_get_status", prompt)
        self.assertNotIn("runtime_update_loop", prompt)


if __name__ == "__main__":
    unittest.main()
