from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pkuclaw.core.models import CodeAgentSettings


RUNTIME_CONFIG_FILE = "agent.toml"


@dataclass(frozen=True)
class RuntimeCodexConfig:
    sandbox: str | None = None
    timeout_seconds: int | None = None


@dataclass(frozen=True)
class RuntimeMonitorConfig:
    scan_interval_seconds: int | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    path: Path
    code_agent: CodeAgentSettings
    codex: RuntimeCodexConfig
    monitor: RuntimeMonitorConfig


class RuntimeConfigLoader:
    """Reads agent-editable runtime config on demand."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir

    @property
    def path(self) -> Path:
        return self.config_dir / RUNTIME_CONFIG_FILE

    def read(self) -> RuntimeConfig:
        raw = _read_toml_if_exists(self.path)
        code_agent_raw = _section(raw, "code_agent")
        codex_raw = _section(raw, "codex")
        monitor_raw = _section(raw, "monitor")
        return RuntimeConfig(
            path=self.path,
            code_agent=CodeAgentSettings(
                provider=_optional_str(code_agent_raw, "provider"),
                mode=_optional_str(code_agent_raw, "mode"),
                model=_optional_str(code_agent_raw, "model"),
                reasoning_effort=_optional_str(code_agent_raw, "reasoning_effort"),
            ),
            codex=RuntimeCodexConfig(
                sandbox=_optional_str(codex_raw, "sandbox"),
                timeout_seconds=_optional_int(codex_raw, "timeout_seconds"),
            ),
            monitor=RuntimeMonitorConfig(
                scan_interval_seconds=_optional_int(
                    monitor_raw,
                    "scan_interval_seconds",
                ),
            ),
        )


def _read_toml_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    if not isinstance(data, dict):
        raise RuntimeError(f"runtime config must be a TOML table: {path}")
    return data


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise RuntimeError(f"runtime config section [{key}] must be a table")
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
