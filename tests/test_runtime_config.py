from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from pkuclaw.core import logging as log
from pkuclaw.core.models import AgentResult
from pkuclaw.core.store import Store
from pkuclaw.loop import LoopManager
from pkuclaw.runtime_config import RuntimeConfigStore

from tests.helpers import (
    FakePopen,
    _core_runtime,
    _settings,
    _wait_for_loop_manager_idle,
    _write_runtime_json,
    _write_test_subskills,
)


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
