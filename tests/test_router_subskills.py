from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pkuclaw.code_agents.subskills import (
    load_skill_registry,
    render_subskills,
    resolve_subskill_names,
)
from pkuclaw.core.router import classify_message

from tests.helpers import _write_skills_json, _write_test_subskills


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
