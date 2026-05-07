from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pkuclaw.core.store import Store
from pkuclaw.mcp.handlers import DaemonMcpToolHandler
from pkuclaw.mcp.server import handle_mcp_request
from pkuclaw.runtime.bootstrap import build_core_runtime_services, build_runtime_bootstrap

from tests.helpers import (
    FakeObject,
    RecordingOutboundBackend,
    _core_runtime,
    _settings,
    _write_runtime_json,
)


class RuntimeBootstrapTests(unittest.TestCase):
    def test_core_runtime_services_own_bootstrap_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root)

            services = build_core_runtime_services(settings, repo_root=root)
            try:
                self.assertIs(services.core_runtime.store, services.store)
                self.assertIs(
                    services.core_runtime.runtime_config,
                    services.runtime_config,
                )
                self.assertIs(
                    services.core_runtime.agent_wrapper,
                    services.agent_wrapper,
                )
                self.assertIs(services.core_runtime.run_executor, services.run_executor)
                self.assertEqual(dict(services.core_runtime.channel_backends), {})
            finally:
                services.run_executor.shutdown(cancel_futures=True)
                services.callback_executor.shutdown(cancel_futures=True)

    def test_mcp_handler_channel_send_text_uses_core_runtime_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root)
            services = build_core_runtime_services(settings, repo_root=root)
            backend = RecordingOutboundBackend(channel="feishu")
            services.core_runtime.register_channel_backend(backend)
            handler = DaemonMcpToolHandler(
                core_runtime=services.core_runtime,
                default_channel="feishu",
            )

            try:
                result = handler.call_tool(
                    "channel_send_text",
                    {"target_id": "oc_chat", "text": "hello via core"},
                )

                self.assertTrue(result.ok)
                self.assertEqual(result.data["message_id"], "om_recorded")
                self.assertEqual(
                    backend.calls,
                    [("send_text", "feishu", "chat_id", "oc_chat", "hello via core")],
                )
                self.assertIn("feishu", services.core_runtime.channel_backends)
            finally:
                services.run_executor.shutdown(cancel_futures=True)
                services.callback_executor.shutdown(cancel_futures=True)

    def test_mcp_tools_list_includes_channel_and_runtime_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            core_runtime = _core_runtime(Path(tmp), store)
            handler = DaemonMcpToolHandler(core_runtime=core_runtime)

            status, response = handle_mcp_request(
                handler,
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )

            self.assertEqual(status, 200)
            names = {tool["name"] for tool in response["result"]["tools"]}
            self.assertIn("channel_send_text", names)
            self.assertIn("channel_send_card", names)
            self.assertIn("channel_send_image", names)
            self.assertIn("channel_update_card", names)
            self.assertIn("runtime_get_status", names)
            self.assertIn("runtime_get_config", names)
            self.assertIn("runtime_list_loops", names)
            self.assertIn("runtime_list_recent_runs", names)
            self.assertIn("runtime_get_run", names)
            self.assertIn("runtime_add_loop", names)
            self.assertTrue(all("pku3b" not in name for name in names))

    def test_mcp_runtime_get_status_returns_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            core_runtime = _core_runtime(Path(tmp), store)
            handler = DaemonMcpToolHandler(core_runtime=core_runtime)

            status, response = handle_mcp_request(
                handler,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "runtime_get_status",
                        "arguments": {},
                    },
                },
            )

            self.assertEqual(status, 200)
            self.assertFalse(response["result"]["isError"])
            payload = json.loads(response["result"]["content"][0]["text"])
            self.assertTrue(payload["ok"])
            self.assertIn("runtime_config_path", payload["data"])
            self.assertIn("run_counts", payload["data"])

    def test_mcp_unknown_tool_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "pkuclaw.db")
            core_runtime = _core_runtime(Path(tmp), store)
            handler = DaemonMcpToolHandler(core_runtime=core_runtime)

            status, response = handle_mcp_request(
                handler,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "does_not_exist", "arguments": {}},
                },
            )

            self.assertEqual(status, 200)
            self.assertIn("error", response)
            self.assertIn("unknown tool", response["error"]["message"])

    def test_mcp_runtime_write_tool_calls_core_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_json(root / "runtime")
            store = Store(root / "pkuclaw.db")
            core_runtime = _core_runtime(root, store)
            handler = DaemonMcpToolHandler(core_runtime=core_runtime)

            result = handler.call_tool("runtime_disable_loop", {"loop_id": "sync_notices"})

            self.assertTrue(result.ok)
            self.assertEqual(result.data["action"], "runtime_disable_loop")
            self.assertEqual(result.data["audit"]["status"], "recorded")
            loops = {loop["id"]: loop for loop in core_runtime.runtime_list_loops()}
            self.assertFalse(loops["sync_notices"]["enabled"])
            self.assertEqual(store.runtime_changes()[0].action, "runtime_disable_loop")

    def test_mcp_layer_has_no_direct_feishu_backend_imports(self) -> None:
        forbidden_modules = {
            "pkuclaw.channels.feishu",
            "pkuclaw.channels.feishu.tools",
            "pkuclaw.channels.feishu.gateway",
            "pkuclaw.channels.feishu.handlers",
        }
        forbidden_names = {
            "FeishuChannelOutboundBackend",
            "FeishuRealtimeGateway",
            "FeishuEventHandlers",
            "FeishuCardKitClient",
        }
        for source_path in Path("pkuclaw/mcp").glob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            imported_modules: set[str] = set()
            imported_names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.add(node.module)
                    imported_names.update(alias.name for alias in node.names)
                elif isinstance(node, ast.Import):
                    imported_names.update(alias.name for alias in node.names)

            self.assertTrue(imported_modules.isdisjoint(forbidden_modules), source_path)
            self.assertTrue(imported_names.isdisjoint(forbidden_names), source_path)

    def test_agent_wrapper_has_no_runtime_write_or_daemon_control_calls(self) -> None:
        source_path = Path("pkuclaw/agents/wrapper.py")
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        forbidden_modules = {
            "pkuclaw.loop",
            "pkuclaw.mcp.server",
            "pkuclaw.channels.feishu.gateway",
            "pkuclaw.channels.feishu.handlers",
        }
        forbidden_names = {"LoopManager", "DaemonMcpServer", "FeishuEventHandlers"}
        forbidden_call_names = {
            "write_runtime_patch",
            "add_loop",
            "update_loop",
            "enable_loop",
            "disable_loop",
            "backup_current",
            "atomic_write_json",
            "_backup_current",
            "_atomic_write_json",
            "_validate_config",
            "attach_loop_manager",
            "serve_forever",
        }
        imported_modules: set[str] = set()
        imported_names: set[str] = set()
        call_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    call_names.add(func.attr)
                elif isinstance(func, ast.Name):
                    call_names.add(func.id)

        self.assertTrue(imported_modules.isdisjoint(forbidden_modules))
        self.assertTrue(imported_names.isdisjoint(forbidden_names))
        self.assertTrue(call_names.isdisjoint(forbidden_call_names))

    def test_loop_manager_does_not_import_or_call_agent_wrapper(self) -> None:
        source_path = Path("pkuclaw/loop.py")
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules: set[str] = set()
        names: set[str] = set()
        attributes: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                attributes.add(node.attr)

        self.assertNotIn("pkuclaw.agents.wrapper", imported_modules)
        self.assertNotIn("AgentWrapper", names)
        self.assertNotIn("agent_wrapper", attributes)

    def test_feishu_gateway_stays_transport_only(self) -> None:
        source_path = Path("pkuclaw/channels/feishu/gateway.py")
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        forbidden_modules = {
            "pkuclaw.agents",
            "pkuclaw.agents.wrapper",
            "pkuclaw.core.store",
            "pkuclaw.loop",
            "pkuclaw.mcp",
            "pkuclaw.mcp.server",
            "pkuclaw.runtime_config",
        }
        forbidden_names = {
            "AgentWrapper",
            "DaemonMcpServer",
            "LoopManager",
            "RuntimeConfigStore",
            "Store",
        }
        imported_modules: set[str] = set()
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)

        self.assertTrue(imported_modules.isdisjoint(forbidden_modules))
        self.assertTrue(imported_names.isdisjoint(forbidden_names))

    def test_feishu_realtime_bootstrap_path_disables_mcp_and_loop_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root)
            backend = RecordingOutboundBackend(channel="feishu")
            fake_gateway = FakeObject(
                channel="feishu",
                channel_backend=backend,
                start=lambda: None,
            )
            with (
                patch(
                    "pkuclaw.runtime.bootstrap.build_feishu_realtime_gateway",
                    return_value=fake_gateway,
                ) as gateway_builder,
                patch("pkuclaw.runtime.bootstrap._start_mcp_thread") as mcp_start,
                patch("pkuclaw.runtime.bootstrap._start_loop_manager") as loop_start,
            ):
                bootstrap = build_runtime_bootstrap(
                    settings,
                    enable_loop=False,
                    enable_mcp=False,
                )

            try:
                gateway_builder.assert_called_once()
                mcp_start.assert_not_called()
                loop_start.assert_not_called()
                self.assertIsNone(bootstrap.loop_manager)
                self.assertIsNone(bootstrap.mcp_server)
                self.assertEqual(bootstrap.threads, ())
                self.assertIn("feishu", bootstrap.services.core_runtime.channel_backends)
            finally:
                bootstrap.services.run_executor.shutdown(cancel_futures=True)
                bootstrap.services.callback_executor.shutdown(cancel_futures=True)
