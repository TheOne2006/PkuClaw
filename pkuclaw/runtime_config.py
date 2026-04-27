from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pkuclaw.core.models import AgentSettings


RUNTIME_CONFIG_FILE = "agent.json"


@dataclass(frozen=True)
class RuntimeCodexConfig:
    sandbox: str | None = None
    timeout_seconds: int | None = None


@dataclass(frozen=True)
class RuntimeLoopConfig:
    interval_seconds: int | None = None
    prompt: str = ""
    skill_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimePromptConfig:
    fragment_paths: tuple[str, ...] = ()
    default_skill_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeNotificationConfig:
    policy: str = "important_only"


@dataclass(frozen=True)
class RuntimeConfig:
    path: Path
    agent: AgentSettings
    codex: RuntimeCodexConfig
    loop: RuntimeLoopConfig
    prompt: RuntimePromptConfig
    notifications: RuntimeNotificationConfig
    warnings: tuple[str, ...] = field(default_factory=tuple)


class RuntimeConfigLoader:
    """Reads agent-editable JSON runtime config on demand with visible fallback."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir
        self._last_valid: RuntimeConfig | None = None

    @property
    def path(self) -> Path:
        return self.config_dir / RUNTIME_CONFIG_FILE

    def read(self) -> RuntimeConfig:
        try:
            config = self._read_valid()
        except Exception as exc:
            warning = f"runtime config fallback: {exc}"
            base = self._last_valid or _default_config(self.path)
            return _with_warning(base, warning)
        self._last_valid = config
        return config

    def _read_valid(self) -> RuntimeConfig:
        if not self.path.exists():
            raise FileNotFoundError(f"runtime config not found: {self.path}")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError(f"runtime config must be a JSON object: {self.path}")

        agent_raw = _section(raw, "agent")
        codex_raw = _section(raw, "codex")
        loop_raw = _section(raw, "loop")
        prompt_raw = _section(raw, "prompt")
        notifications_raw = _section(raw, "notifications")
        return RuntimeConfig(
            path=self.path,
            agent=AgentSettings(
                provider=_optional_str(agent_raw, "provider"),
                mode=_optional_str(agent_raw, "mode"),
                model=_optional_str(agent_raw, "model"),
                reasoning_effort=_optional_str(agent_raw, "reasoning_effort"),
            ),
            codex=RuntimeCodexConfig(
                sandbox=_optional_str(codex_raw, "sandbox"),
                timeout_seconds=_optional_int(codex_raw, "timeout_seconds"),
            ),
            loop=RuntimeLoopConfig(
                interval_seconds=_optional_int(loop_raw, "interval_seconds"),
                prompt=_optional_str(loop_raw, "prompt") or "",
                skill_names=_optional_str_tuple(loop_raw, "skill_names"),
            ),
            prompt=RuntimePromptConfig(
                fragment_paths=_optional_str_tuple(prompt_raw, "fragment_paths"),
                default_skill_names=_optional_str_tuple(
                    prompt_raw,
                    "default_skill_names",
                ),
            ),
            notifications=RuntimeNotificationConfig(
                policy=_optional_str(notifications_raw, "policy") or "important_only",
            ),
        )


def _default_config(path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        path=path,
        agent=AgentSettings(provider="codex", mode="standard"),
        codex=RuntimeCodexConfig(sandbox="workspace-write", timeout_seconds=1800),
        loop=RuntimeLoopConfig(
            interval_seconds=900,
            prompt="检查课程状态、教学网通知和本地数据。如果没有重要变化，保持静默。",
            skill_names=("tasks/sync-notices.md",),
        ),
        prompt=RuntimePromptConfig(),
        notifications=RuntimeNotificationConfig(),
    )


def _with_warning(config: RuntimeConfig, warning: str) -> RuntimeConfig:
    return RuntimeConfig(
        path=config.path,
        agent=config.agent,
        codex=config.codex,
        loop=config.loop,
        prompt=config.prompt,
        notifications=config.notifications,
        warnings=(*config.warnings, warning),
    )


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise RuntimeError(f"runtime config section {key} must be an object")
    return value


def _optional_str(section: dict[str, Any], key: str) -> str | None:
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"runtime config value {key} must be a string")
    value = value.strip()
    return value or None


def _optional_int(section: dict[str, Any], key: str) -> int | None:
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise RuntimeError(f"runtime config value {key} must be an integer")
    return value


def _optional_str_tuple(section: dict[str, Any], key: str) -> tuple[str, ...]:
    value = section.get(key)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise RuntimeError(f"runtime config value {key} must be a string array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise RuntimeError(f"runtime config value {key} must be a string array")
        stripped = item.strip()
        if stripped:
            result.append(stripped)
    return tuple(result)
