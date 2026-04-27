from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from pkuclaw.backbone import TeachingBackbone
from pkuclaw.channels.feishu import handle_text_message
from pkuclaw.config import AppConfig, CodexConfig, FeishuConfig, MonitorConfig, Pku3bConfig, Settings
from pkuclaw.core import logging as log
from pkuclaw.core.app import CoreLoop
from pkuclaw.core.models import ChannelMessage
from pkuclaw.core.router import classify_message
from pkuclaw.core.store import Store
from pkuclaw.workers.codex import CodexWorker


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

    def test_feishu_handler_returns_ack(self) -> None:
        self.assertIn("Codex worker", handle_text_message("你好"))


class StoreAndCoreLoopTests(unittest.TestCase):
    def test_conversation_mode_and_local_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            loop = CoreLoop(
                store=store,
                codex_worker=_fake_codex_worker(Path(tmp), store),
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
            self.assertEqual(conversation.mode, "fast")

    def test_user_message_creates_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            loop = CoreLoop(
                store=store,
                codex_worker=_fake_codex_worker(Path(tmp), store),
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


class CodexWorkerTests(unittest.TestCase):
    def test_worker_persists_result_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root)
            store = Store(settings.app.data_dir / "pkuclaw.db")
            plan = classify_message("你好")
            run = store.create_run(
                conversation_id="feishu:user:open-1",
                user_text="你好",
                intent=plan.intent,
            )

            def fake_run(command, **kwargs):
                output_path = Path(command[command.index("-o") + 1])
                output_path.write_text("## 回复用户\nhello\n", encoding="utf-8")
                return CompletedProcess(
                    command,
                    0,
                    stdout='{"thread_id":"thread-abc","text":"hello"}\n',
                    stderr="",
                )

            with (
                patch("pkuclaw.workers.codex.subprocess.run", side_effect=fake_run),
                patch.object(log.console, "print"),
            ):
                result = CodexWorker(
                    settings=settings,
                    store=store,
                    repo_root=root,
                ).run(run, plan)

            self.assertEqual(result.status, "succeeded")
            self.assertEqual(result.session_id, "thread-abc")
            self.assertTrue(result.result_path.exists())
            conversation = store.ensure_conversation("feishu:user:open-1")
            self.assertEqual(conversation.codex_session_id, "thread-abc")


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


def _fake_codex_worker(root: Path, store: Store) -> CodexWorker:
    return CodexWorker(settings=_settings(root), store=store, repo_root=root)


def _settings(root: Path) -> Settings:
    return Settings(
        config_path=root / "config.toml",
        app=AppConfig(name="test", data_dir=root / "data", timezone="Asia/Shanghai"),
        feishu=FeishuConfig(
            app_id="cli_test",
            app_secret=None,
            app_secret_env="FEISHU_APP_SECRET",
            event_mode="websocket",
        ),
        pku3b=Pku3bConfig(bin=root / "pku3b", source_dir=root / "pku3b-src"),
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
