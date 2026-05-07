from __future__ import annotations

import io
import json
import time
from pathlib import Path

from pkuclaw.agents.wrapper import AgentWrapper
from pkuclaw.channels.base import ChannelOutboundResult, ChannelTarget
from pkuclaw.channels.feishu.cards import FeishuCardKitClient
from pkuclaw.config import (
    AgentConfig,
    AppConfig,
    CodexConfig,
    FeishuConfig,
    McpConfig,
    MonitorConfig,
    Settings,
)
from pkuclaw.core.app import CoreRuntime
from pkuclaw.core.models import AgentEvent
from pkuclaw.core.store import Store
from pkuclaw.loop import LoopManager
from pkuclaw.runtime_config import RuntimeConfigStore


def _write_test_subskills(root: Path) -> None:
    files = {
        "runtime/codex-subagent.md": "# Codex runtime\n",
        "tasks/write-notes.md": "# Write notes\n",
        "tasks/do-homework.md": "# Do homework\n",
        "tasks/sync-notices.md": "# Sync notices\n",
        "tools/pdf-reader.md": "# PDF reader\n",
        "tools/pku3b-setup.md": "# pku3b setup\n",
        "tools/data-parser.md": "# Data parser\n",
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _write_skills_json(
    runtime_dir: Path,
    *,
    skills: list[dict] | None = None,
) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 1,
        "skills": skills
        or [
            {
                "name": "runtime/codex-subagent.md",
                "intent": "runtime",
                "dependencies": [],
                "allowed_sources": ["realtime", "loop", "mcp", "manual", "system"],
                "requires_confirmation": False,
            },
            {
                "name": "tasks/sync-notices.md",
                "intent": "sync",
                "dependencies": ["tools/pku3b-setup.md", "tools/data-parser.md"],
                "allowed_sources": ["realtime", "loop"],
                "requires_confirmation": False,
            },
            {
                "name": "tasks/do-homework.md",
                "intent": "homework",
                "dependencies": ["tools/pdf-reader.md", "tools/pku3b-setup.md"],
                "allowed_sources": ["realtime"],
                "requires_confirmation": True,
            },
            {
                "name": "tasks/write-notes.md",
                "intent": "notes",
                "dependencies": ["tools/pdf-reader.md"],
                "allowed_sources": ["realtime", "loop"],
                "requires_confirmation": False,
            },
            {
                "name": "tools/pku3b-setup.md",
                "intent": "tool",
                "dependencies": [],
                "allowed_sources": ["realtime", "loop", "mcp", "manual", "system"],
                "requires_confirmation": False,
            },
            {
                "name": "tools/data-parser.md",
                "intent": "tool",
                "dependencies": [],
                "allowed_sources": ["realtime", "loop", "mcp", "manual", "system"],
                "requires_confirmation": False,
            },
            {
                "name": "tools/pdf-reader.md",
                "intent": "tool",
                "dependencies": [],
                "allowed_sources": ["realtime", "loop", "mcp", "manual", "system"],
                "requires_confirmation": False,
            },
        ],
    }
    (runtime_dir / "skills.json").write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )


def _feishu_chat_target() -> ChannelTarget:
    return ChannelTarget(
        channel="feishu",
        target_type="chat_id",
        target_id="oc_chat",
    )


def _element_tags(card: dict) -> set[str]:
    tags: set[str] = set()

    def collect(value) -> None:
        if isinstance(value, dict):
            tag = value.get("tag")
            if isinstance(tag, str):
                tags.add(tag)
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(card)
    return tags


def _markdown_contents(card: dict) -> list[str]:
    contents: list[str] = []

    def collect(value) -> None:
        if isinstance(value, dict):
            if value.get("tag") == "markdown":
                content = value.get("content")
                if isinstance(content, str):
                    contents.append(content)
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(card)
    return contents


def _buttons(card: dict) -> list[dict]:
    buttons: list[dict] = []

    def collect(value) -> None:
        if isinstance(value, dict):
            if value.get("tag") == "button":
                buttons.append(value)
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(card)
    return buttons


class CapturingSink:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def emit(self, event: AgentEvent) -> None:
        self.events.append(event)


class RecordingOutboundBackend:
    def __init__(self, *, channel: str) -> None:
        self.channel = channel
        self.calls: list[tuple] = []

    def send_text(self, *, target: ChannelTarget, text: str) -> ChannelOutboundResult:
        self.calls.append(
            ("send_text", target.channel, target.target_type, target.target_id, text)
        )
        return ChannelOutboundResult(
            ok=True,
            message="recorded text",
            target=target,
            external_message_id="om_recorded",
            external_card_id="card_recorded",
            data={"message_id": "om_recorded", "card_id": "card_recorded"},
        )

    def send_card(
        self,
        *,
        target: ChannelTarget,
        card: dict,
    ) -> ChannelOutboundResult:
        self.calls.append(("send_card", target.channel, target.target_id, card))
        return ChannelOutboundResult(ok=True, message="recorded card", target=target)

    def send_image(
        self,
        *,
        target: ChannelTarget,
        image_path: str,
    ) -> ChannelOutboundResult:
        self.calls.append(("send_image", target.channel, target.target_id, image_path))
        return ChannelOutboundResult(ok=True, message="recorded image", target=target)

    def update_card(
        self,
        *,
        card_id: str,
        card: dict,
        sequence: int,
    ) -> ChannelOutboundResult:
        self.calls.append(("update_card", card_id, card, sequence))
        return ChannelOutboundResult(ok=True, message="recorded update")


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
    def __init__(
        self,
        *,
        message_id: str | None = None,
        card_id: str | None = None,
    ) -> None:
        self.message_id = message_id
        self.card_id = card_id


class FakeResponse:
    code = 0
    msg = "ok"
    raw = None

    def __init__(self, data: FakeResponseData | None = None) -> None:
        self.data = data or FakeResponseData()

    def success(self) -> bool:
        return True

    def get_log_id(self) -> str:
        return "log-id"


class FakeMessageResource:
    def __init__(self) -> None:
        self.created = None

    def create(self, request):
        self.created = request
        return FakeResponse(FakeResponseData(message_id="om_1"))


class FakeCardResource:
    def __init__(self) -> None:
        self.created = None
        self.updated = None
        self.update_count = 0

    def create(self, request):
        self.created = request
        return FakeResponse(FakeResponseData(card_id="card_1"))

    def update(self, request):
        self.updated = request
        self.update_count += 1
        return FakeResponse()


class FakeFeishuApi:
    def __init__(self) -> None:
        self.im = FakeObject(
            v1=FakeObject(
                message=FakeMessageResource(),
            )
        )
        self.cardkit = FakeObject(
            v1=FakeObject(
                card=FakeCardResource(),
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

    def card_id(self, value):
        self.target.card_id = value
        return self

    def type(self, value):
        self.target.type = value
        return self

    def data(self, value):
        self.target.data = value
        return self

    def card(self, value):
        self.target.card = value
        return self

    def uuid(self, value):
        self.target.uuid = value
        return self

    def sequence(self, value):
        self.target.sequence = value
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


class FakeCreateCardRequest:
    @staticmethod
    def builder() -> FakeBuilder:
        return FakeBuilder(FakeObject())


class FakeCreateCardRequestBody:
    @staticmethod
    def builder() -> FakeBuilder:
        return FakeBuilder(FakeObject())


class FakeUpdateCardRequest:
    @staticmethod
    def builder() -> FakeBuilder:
        return FakeBuilder(FakeObject())


class FakeUpdateCardRequestBody:
    @staticmethod
    def builder() -> FakeBuilder:
        return FakeBuilder(FakeObject())


class FakeCardModel:
    @staticmethod
    def builder() -> FakeBuilder:
        return FakeBuilder(FakeObject())


def _fake_feishu_cardkit_client(fake_api: FakeFeishuApi) -> FeishuCardKitClient:
    return FeishuCardKitClient(
        lark=FakeLark(),
        client=fake_api,
        create_message_request=FakeCreateMessageRequest,
        create_message_request_body=FakeCreateMessageRequestBody,
        create_card_request=FakeCreateCardRequest,
        create_card_request_body=FakeCreateCardRequestBody,
        update_card_request=FakeUpdateCardRequest,
        update_card_request_body=FakeUpdateCardRequestBody,
        card_model=FakeCardModel,
    )


def _write_runtime_json(
    runtime_dir: Path,
    *,
    loops: list[dict] | None = None,
    permissions: dict | None = None,
) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 1,
        "agent": {
            "provider": "codex",
            "mode": "standard",
            "model": "",
            "reasoning_effort": "",
        },
        "codex": {
            "sandbox": "workspace-write",
            "timeout_seconds": 1800,
        },
        "loops": loops
        or [
            {
                "id": "sync_notices",
                "enabled": True,
                "interval_seconds": 900,
                "prompt": "sync notices",
                "skill_names": ["tasks/sync-notices.md"],
                "sink_mode": "silent",
                "notify_policy": "important_only",
            }
        ],
        "prompt": {
            "fragment_paths": [],
            "default_skill_names": [],
        },
        "notifications": {
            "policy": "important_only",
        },
        "permissions": permissions
        or {
            "agent_can_update_runtime": True,
            "agent_can_add_loop": True,
            "agent_can_modify_boot_config": False,
        },
    }
    (runtime_dir / "runtime.json").write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )


def _core_runtime(root: Path, store: Store) -> CoreRuntime:
    settings = _settings(root)
    runtime_config = RuntimeConfigStore(root / "runtime")
    return CoreRuntime(
        store=store,
        agent_wrapper=AgentWrapper(
            settings=settings,
            store=store,
            runtime_config=runtime_config,
            repo_root=root,
        ),
        runtime_config=runtime_config,
    )


def _agent_request(
    *,
    conversation_id: str,
    text: str,
    intent: str,
    skill_names: tuple[str, ...],
):
    from pkuclaw.core.models import AgentRunRequest

    return AgentRunRequest(
        source="realtime",
        conversation_id=conversation_id,
        text=text,
        intent=intent,
        skill_names=skill_names,
        channel="feishu",
        sender_id="open-1",
        sink_mode="streaming",
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
        agent=AgentConfig(provider="codex"),
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
        mcp=McpConfig(host="127.0.0.1", port=8765),
    )


def _wait_for_loop_manager_idle(manager: LoopManager, *, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not manager._active_by_loop:  # noqa: SLF001 - assert scheduler state in tests
            return
        time.sleep(0.01)
    raise AssertionError("LoopManager did not become idle")
