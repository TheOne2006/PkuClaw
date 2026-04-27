from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("configs/config.toml")
EXAMPLE_CONFIG_PATH = Path("configs/config.example.toml")
DEFAULT_FEISHU_API_BASE = "https://open.feishu.cn"


@dataclass(frozen=True)
class AppConfig:
    name: str
    data_dir: Path
    timezone: str


@dataclass(frozen=True)
class FeishuConfig:
    app_id: str
    app_secret: str | None
    app_secret_env: str
    event_mode: str
    api_base: str = DEFAULT_FEISHU_API_BASE

    def resolve_app_secret(self) -> str:
        if self.app_secret:
            return self.app_secret
        value = os.environ.get(self.app_secret_env, "").strip()
        if not value:
            raise RuntimeError(
                f"missing Feishu app secret in environment variable {self.app_secret_env}"
            )
        return value


@dataclass(frozen=True)
class Pku3bConfig:
    bin: Path
    source_dir: Path


@dataclass(frozen=True)
class CodexConfig:
    bin: str
    sandbox: str
    model: str | None
    timeout_seconds: int
    max_concurrent_runs: int


@dataclass(frozen=True)
class MonitorConfig:
    scan_interval_seconds: int
    enable_assignments: bool
    enable_announcements: bool
    enable_replays: bool
    enable_grades: bool


@dataclass(frozen=True)
class Settings:
    config_path: Path
    app: AppConfig
    feishu: FeishuConfig
    pku3b: Pku3bConfig
    codex: CodexConfig
    monitor: MonitorConfig


def load_settings(config_path: Path | None = None) -> Settings:
    path = _resolve_config_path(config_path)
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    app_raw = _get_section(raw, "app")
    feishu_raw = _get_section(raw, "feishu")
    pku3b_raw = _get_section(raw, "pku3b")
    codex_raw = _get_section(raw, "codex")
    monitor_raw = _get_section(raw, "monitor")

    app = AppConfig(
        name=_read_str(app_raw, "name", default="PkuClaw"),
        data_dir=Path(_read_str(app_raw, "data_dir", default="data")),
        timezone=_read_str(app_raw, "timezone", default="Asia/Shanghai"),
    )
    feishu = FeishuConfig(
        app_id=os.environ.get("FEISHU_APP_ID", "").strip()
        or _read_str(feishu_raw, "app_id"),
        app_secret=_read_optional_str(feishu_raw, "app_secret"),
        app_secret_env=_read_str(
            feishu_raw, "app_secret_env", default="FEISHU_APP_SECRET"
        ),
        event_mode=_read_str(feishu_raw, "event_mode", default="websocket").lower(),
        api_base=os.environ.get("FEISHU_API_BASE", "").strip()
        or _read_str(feishu_raw, "api_base", default=DEFAULT_FEISHU_API_BASE),
    )
    pku3b = Pku3bConfig(
        bin=Path(_read_str(pku3b_raw, "bin", default="crates/pku3b/target/debug/pku3b")),
        source_dir=Path(_read_str(pku3b_raw, "source_dir", default="crates/pku3b")),
    )
    codex = CodexConfig(
        bin=_read_str(codex_raw, "bin", default="codex"),
        sandbox=_read_str(codex_raw, "sandbox", default="workspace-write"),
        model=_read_optional_str(codex_raw, "model"),
        timeout_seconds=max(30, _read_int(codex_raw, "timeout_seconds", default=1800)),
        max_concurrent_runs=max(
            1, _read_int(codex_raw, "max_concurrent_runs", default=1)
        ),
    )
    monitor = MonitorConfig(
        scan_interval_seconds=max(
            1, _read_int(monitor_raw, "scan_interval_seconds", default=900)
        ),
        enable_assignments=_read_bool(
            monitor_raw, "enable_assignments", default=True
        ),
        enable_announcements=_read_bool(
            monitor_raw, "enable_announcements", default=True
        ),
        enable_replays=_read_bool(monitor_raw, "enable_replays", default=True),
        enable_grades=_read_bool(monitor_raw, "enable_grades", default=False),
    )
    return Settings(
        config_path=path,
        app=app,
        feishu=feishu,
        pku3b=pku3b,
        codex=codex,
        monitor=monitor,
    )


def _resolve_config_path(config_path: Path | None) -> Path:
    if config_path is not None:
        path = config_path.expanduser()
        if not path.exists():
            raise FileNotFoundError(f"config file not found: {path}")
        return path
    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH
    if EXAMPLE_CONFIG_PATH.exists():
        return EXAMPLE_CONFIG_PATH
    raise FileNotFoundError(
        f"config file not found: {DEFAULT_CONFIG_PATH} or {EXAMPLE_CONFIG_PATH}"
    )


def _get_section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    section = raw.get(name, {})
    if not isinstance(section, dict):
        raise RuntimeError(f"config section [{name}] must be a table")
    return section


def _read_str(section: dict[str, Any], key: str, default: str | None = None) -> str:
    value = section.get(key, default)
    if value is None:
        raise RuntimeError(f"missing config value: {key}")
    if not isinstance(value, str):
        raise RuntimeError(f"config value {key} must be a string")
    return value.strip()


def _read_optional_str(section: dict[str, Any], key: str) -> str | None:
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"config value {key} must be a string")
    value = value.strip()
    return value or None


def _read_bool(section: dict[str, Any], key: str, default: bool) -> bool:
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise RuntimeError(f"config value {key} must be a boolean")
    return value


def _read_int(section: dict[str, Any], key: str, default: int) -> int:
    value = section.get(key, default)
    if not isinstance(value, int):
        raise RuntimeError(f"config value {key} must be an integer")
    return value
