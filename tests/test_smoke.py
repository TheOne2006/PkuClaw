"""Smoke tests for the packaged PkuClaw runtime."""
from __future__ import annotations

import importlib
import unittest


class PackageSmokeTests(unittest.TestCase):
    """Keep CI meaningful even before domain-specific tests exist."""

    def test_runtime_modules_import(self) -> None:
        modules = [
            "pkuclaw",
            "pkuclaw.cli",
            "pkuclaw.config",
            "pkuclaw.channels.feishu",
            "pkuclaw.core.runtime",
            "pkuclaw.runtime.bootstrap",
        ]
        for module in modules:
            with self.subTest(module=module):
                self.assertIsNotNone(importlib.import_module(module))


if __name__ == "__main__":
    unittest.main()
