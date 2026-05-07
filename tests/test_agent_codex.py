from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pkuclaw.agents.wrapper import AgentWrapper
from pkuclaw.core import logging as log
from pkuclaw.core.router import classify_message
from pkuclaw.core.store import Store
from pkuclaw.runtime_config import RuntimeConfigStore

from tests.helpers import (
    CapturingSink,
    FakePopen,
    _agent_request,
    _settings,
    _write_runtime_json,
    _write_skills_json,
    _write_test_subskills,
)


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
