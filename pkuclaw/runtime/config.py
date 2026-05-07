"""Hot-load runtime.json and validate editable runtime files."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from pkuclaw.core.models import (
    DEFAULT_AGENT_MODE,
    DEFAULT_AGENT_MODEL,
    DEFAULT_AGENT_PROVIDER,
    DEFAULT_AGENT_REASONING_EFFORT,
    AgentSettings,
)


RUNTIME_CONFIG_FILE = "runtime.json"
RUNTIME_BACKUP_DIR = "backups"
SUPPORTED_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RuntimeCodexConfig:
    """runtime.json 中可热加载的 Codex 配置覆盖。"""
    sandbox: str | None = None
    timeout_seconds: int | None = None


@dataclass(frozen=True)
class RuntimeLoopConfig:
    """runtime.json 中一条周期任务 loop spec。"""
    id: str = "sync_notices"
    enabled: bool = True
    interval_seconds: int | None = None
    prompt: str = ""
    skill_names: tuple[str, ...] = ()
    sink_mode: str = "silent"
    notify_policy: str = "important_only"
    default_channel: str | None = None
    default_target_type: str | None = None
    default_target_id: str | None = None
    prevent_overlap: bool = True
    max_concurrent_runs: int | None = None


@dataclass(frozen=True)
class RuntimeNotificationConfig:
    """runtime.json 中的通知策略配置。"""
    policy: str = "important_only"


@dataclass(frozen=True)
class RuntimeConfig:
    """校验后的 runtime.json 快照。"""
    path: Path
    schema_version: int
    agent: AgentSettings
    codex: RuntimeCodexConfig
    loops: tuple[RuntimeLoopConfig, ...]
    notifications: RuntimeNotificationConfig
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RuntimeConfigWriteResult:
    """一次安全写 runtime.json 后的结果和审计摘要。"""
    action: str
    file: Path
    backup_path: Path | None
    old_hash: str | None
    new_hash: str
    diff_summary: str
    status: str
    config: RuntimeConfig


class RuntimeConfigStore:
    """Hot-loaded runtime config store.

    Runtime files are ordinary editable files; these helpers only provide validated local writes for non-MCP callers.
    """

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir
        self._last_valid: RuntimeConfig | None = None
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        """Canonical live runtime config file."""
        return self.config_dir / RUNTIME_CONFIG_FILE

    @property
    def backups_dir(self) -> Path:
        """Directory for automatic pre-write backups."""
        return self.config_dir / RUNTIME_BACKUP_DIR

    def read_snapshot(self) -> RuntimeConfig:
        """Read and validate runtime.json, falling back to last valid/defaults."""

        with self._lock:
            try:
                config = self._read_valid()
            except Exception as exc:
                # Broken live config must not take down the daemon; keep serving
                # with the previous validated snapshot and surface a warning.
                warning = f"runtime config fallback: {exc}"
                base = self._last_valid or _default_config(self.path)
                return _with_warning(base, warning)
            self._last_valid = config
            return config

    def add_loop(self, loop: Mapping[str, Any]) -> RuntimeConfigWriteResult:
        """校验新 loop，避免重复 id，然后走安全提交路径写入 runtime.json。"""
        if not isinstance(loop, Mapping):
            raise RuntimeError("loop must be an object")
        normalized_loop = _loop_config_to_raw(_parse_loop(loop, index=0, seen=set()))
        loop_id = str(normalized_loop["id"])
        with self._lock:
            raw = _config_to_raw(self.read_snapshot())
            loops = _object_list(raw, "loops")
            if any(item.get("id") == loop_id for item in loops if isinstance(item, dict)):
                raise RuntimeError(f"duplicate runtime loop id: {loop_id}")
            raw["loops"] = [*loops, normalized_loop]
            return self._commit_candidate(
                raw,
                action="add_loop",
                diff_summary=f"add loop {loop_id}",
            )

    def update_loop(
        self,
        loop_id: str,
        updates: Mapping[str, Any],
        *,
        action: str = "update_loop",
    ) -> RuntimeConfigWriteResult:
        """合并单个 loop 的允许字段，重新校验后安全写入。"""
        loop_id = _validate_loop_id_value(loop_id)
        if not isinstance(updates, Mapping):
            raise RuntimeError("loop updates must be an object")
        unexpected = sorted(set(updates) - _LOOP_UPDATE_KEYS)
        if unexpected:
            raise RuntimeError(f"unexpected loop update keys: {', '.join(unexpected)}")
        if "id" in updates and str(updates.get("id") or "").strip() != loop_id:
            raise RuntimeError("runtime loop id cannot be changed")
        with self._lock:
            raw = _config_to_raw(self.read_snapshot())
            loops = _object_list(raw, "loops")
            updated: list[dict[str, Any]] = []
            found = False
            for item in loops:
                if not isinstance(item, dict):
                    raise RuntimeError("runtime config value loops must be an object array")
                if item.get("id") != loop_id:
                    updated.append(copy.deepcopy(item))
                    continue
                candidate_loop = _deep_merge(item, dict(updates))
                normalized_loop = _loop_config_to_raw(
                    _parse_loop(candidate_loop, index=len(updated), seen=set())
                )
                updated.append(normalized_loop)
                found = True
            if not found:
                raise RuntimeError(f"runtime loop not found: {loop_id}")
            raw["loops"] = updated
            return self._commit_candidate(
                raw,
                action=action,
                diff_summary=_loop_update_summary(action, loop_id, updates),
            )

    def enable_loop(self, loop_id: str) -> RuntimeConfigWriteResult:
        """把指定 loop 的 enabled 字段设为 true。"""
        return self.update_loop(
            loop_id,
            {"enabled": True},
            action="enable_loop",
        )

    def disable_loop(self, loop_id: str) -> RuntimeConfigWriteResult:
        """把指定 loop 的 enabled 字段设为 false。"""
        return self.update_loop(
            loop_id,
            {"enabled": False},
            action="disable_loop",
        )

    def _backup_current(self) -> Path | None:
        """Copy the current runtime.json to backups/ before a write."""

        with self._lock:
            if not self.path.exists():
                return None
            self.backups_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            candidate = self.backups_dir / f"runtime.{stamp}.json"
            suffix = 1
            while candidate.exists():
                candidate = self.backups_dir / f"runtime.{stamp}.{suffix}.json"
                suffix += 1
            shutil.copy2(self.path, candidate)
            return candidate

    def _atomic_write_json(self, data: Mapping[str, Any]) -> None:
        """Write runtime.json via tmp + fsync + atomic rename."""

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_name(f"{self.path.name}.tmp")
            try:
                # fsync the temporary file before os.replace so a crash does not
                # leave a zero-length or partially-written runtime.json.
                with tmp_path.open("w", encoding="utf-8") as handle:
                    handle.write(_json_text(data))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, self.path)
                _fsync_directory(self.path.parent)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()

    def _validate_config(self, raw: Mapping[str, Any]) -> RuntimeConfig:
        """校验原始 runtime config 对象并返回规范化 RuntimeConfig。"""
        return _parse_config(raw, path=self.path)

    def _read_valid(self) -> RuntimeConfig:
        """Read runtime.json and reject invalid or unsupported content."""
        if not self.path.exists():
            raise FileNotFoundError(f"runtime config not found: {self.path}")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError(f"runtime config must be a JSON object: {self.path}")
        return self._validate_config(raw)

    def _commit_candidate(
        self,
        candidate: Mapping[str, Any],
        *,
        action: str,
        diff_summary: str,
    ) -> RuntimeConfigWriteResult:
        """对候选配置执行校验、规范化、备份、原子写入和 last_valid 更新。"""
        # Validate before touching disk, then write the normalized representation
        # so future diffs and hashes are stable.
        validated = self._validate_config(candidate)
        normalized = _config_to_raw(validated)
        old_hash = _hash_file(self.path)
        new_hash = _hash_bytes(_json_text(normalized).encode("utf-8"))
        backup_path = self._backup_current()
        self._atomic_write_json(normalized)
        committed = self._validate_config(normalized)
        self._last_valid = committed
        return RuntimeConfigWriteResult(
            action=action,
            file=self.path,
            backup_path=backup_path,
            old_hash=old_hash,
            new_hash=new_hash,
            diff_summary=diff_summary,
            status="written",
            config=committed,
        )


_LOOP_UPDATE_KEYS = {
    "id",
    "enabled",
    "interval_seconds",
    "prompt",
    "skill_names",
    "sink_mode",
    "notify_policy",
    "default_channel",
    "default_target_type",
    "default_target_id",
    "prevent_overlap",
    "max_concurrent_runs",
}


def _default_config(path: Path) -> RuntimeConfig:
    """根据内置默认 raw config 构造 RuntimeConfig。"""
    return _parse_config(_default_raw_config(), path=path)


def _with_warning(config: RuntimeConfig, warning: str) -> RuntimeConfig:
    """复制 RuntimeConfig 并附加一条 fallback warning。"""
    return RuntimeConfig(
        path=config.path,
        schema_version=config.schema_version,
        agent=config.agent,
        codex=config.codex,
        loops=config.loops,
        notifications=config.notifications,
        warnings=(*config.warnings, warning),
    )


def _parse_config(raw: Mapping[str, Any], *, path: Path) -> RuntimeConfig:
    """解析并校验 runtime.json 根对象。"""
    if not isinstance(raw, Mapping):
        raise RuntimeError("runtime config must be a JSON object")

    schema_version = _schema_version(raw)
    agent_raw = _section(raw, "agent")
    codex_raw = _section(raw, "codex")
    notifications_raw = _section(raw, "notifications")
    return RuntimeConfig(
        path=path,
        schema_version=schema_version,
        agent=AgentSettings(
            provider=_optional_str(agent_raw, "provider") or DEFAULT_AGENT_PROVIDER,
            mode=_optional_str(agent_raw, "mode") or DEFAULT_AGENT_MODE,
            model=_optional_str(agent_raw, "model") or DEFAULT_AGENT_MODEL,
            reasoning_effort=(
                _optional_str(agent_raw, "reasoning_effort")
                or DEFAULT_AGENT_REASONING_EFFORT
            ),
        ),
        codex=RuntimeCodexConfig(
            sandbox=_optional_str(codex_raw, "sandbox") or "workspace-write",
            timeout_seconds=_positive_int_or_default(
                codex_raw,
                "timeout_seconds",
                default=1800,
            ),
        ),
        loops=_read_loops(raw),
        notifications=RuntimeNotificationConfig(
            policy=_optional_str(notifications_raw, "policy") or "important_only",
        ),
    )


def _schema_version(raw: Mapping[str, Any]) -> int:
    """读取并校验 schema_version。"""
    value = raw.get("schema_version", SUPPORTED_SCHEMA_VERSION)
    if not isinstance(value, int):
        raise RuntimeError("runtime config value schema_version must be an integer")
    if value != SUPPORTED_SCHEMA_VERSION:
        raise RuntimeError(
            "unsupported runtime config schema_version: "
            f"{value} (supported: {SUPPORTED_SCHEMA_VERSION})"
        )
    return value


def _read_loops(raw: Mapping[str, Any]) -> tuple[RuntimeLoopConfig, ...]:
    """读取 runtime loops，缺省时使用内置默认 loop。"""
    value = raw.get("loops")
    if value is None:
        return _default_loops()
    if not isinstance(value, list):
        raise RuntimeError("runtime config value loops must be an array")
    loops: list[RuntimeLoopConfig] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise RuntimeError("runtime config value loops must be an object array")
        loops.append(_parse_loop(item, index=index, seen=seen))
    return tuple(loops)


def _parse_loop(
    item: Mapping[str, Any],
    *,
    index: int,
    seen: set[str],
) -> RuntimeLoopConfig:
    """解析并校验一条 runtime loop spec。"""
    loop_id = _required_str(item, "id")
    if loop_id in seen:
        raise RuntimeError(f"duplicate runtime loop id: {loop_id}")
    seen.add(loop_id)
    interval_seconds = _optional_int(item, "interval_seconds")
    if interval_seconds is not None and interval_seconds < 1:
        raise RuntimeError("runtime config value interval_seconds must be >= 1")
    default_channel = _optional_str(item, "default_channel")
    default_target_type = _optional_str(item, "default_target_type")
    default_target_id = _optional_str(item, "default_target_id")
    target_values = (default_channel, default_target_type, default_target_id)
    if any(value is not None for value in target_values) and not all(
        value is not None for value in target_values
    ):
        # Partial targets are rejected because MCP notification tools need all
        # three fields to address a channel destination reliably.
        raise RuntimeError(
            "runtime loop default target requires default_channel, "
            "default_target_type, and default_target_id"
        )
    max_concurrent_runs = _optional_int(item, "max_concurrent_runs")
    if max_concurrent_runs is not None and max_concurrent_runs < 1:
        raise RuntimeError("runtime config value max_concurrent_runs must be >= 1")
    return RuntimeLoopConfig(
        id=loop_id,
        enabled=_optional_bool(item, "enabled", default=True),
        interval_seconds=interval_seconds,
        prompt=_optional_str(item, "prompt") or "",
        skill_names=_optional_str_tuple(item, "skill_names"),
        sink_mode=_optional_str(item, "sink_mode") or "silent",
        notify_policy=_optional_str(item, "notify_policy") or "important_only",
        default_channel=default_channel,
        default_target_type=default_target_type,
        default_target_id=default_target_id,
        prevent_overlap=_optional_bool(item, "prevent_overlap", default=True),
        max_concurrent_runs=max_concurrent_runs,
    )


def _default_loops() -> tuple[RuntimeLoopConfig, ...]:
    """返回内置默认 sync_notices loop。"""
    return (
        RuntimeLoopConfig(
            id="sync_notices",
            enabled=True,
            interval_seconds=900,
            prompt="检查课程状态、教学网通知和本地数据。如果没有重要变化，保持静默；如果发现重要变化，使用 channel notification tools 通知用户。",
            skill_names=("tasks/sync-notices.md",),
            sink_mode="silent",
            notify_policy="important_only",
            prevent_overlap=True,
        ),
    )


def _default_raw_config() -> dict[str, Any]:
    """返回可写入磁盘的内置默认 runtime.json。"""
    return {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "agent": {
            "provider": DEFAULT_AGENT_PROVIDER,
            "mode": DEFAULT_AGENT_MODE,
            "model": DEFAULT_AGENT_MODEL,
            "reasoning_effort": DEFAULT_AGENT_REASONING_EFFORT,
        },
        "codex": {
            "sandbox": "workspace-write",
            "timeout_seconds": 1800,
        },
        "loops": [_loop_config_to_raw(loop) for loop in _default_loops()],
        "notifications": {
            "policy": "important_only",
        },
    }


def _config_to_raw(config: RuntimeConfig) -> dict[str, Any]:
    """把 RuntimeConfig 规范化为 JSON 可序列化对象。"""
    return {
        "schema_version": config.schema_version,
        "agent": {
            "provider": config.agent.provider or DEFAULT_AGENT_PROVIDER,
            "mode": config.agent.mode or DEFAULT_AGENT_MODE,
            "model": config.agent.model or DEFAULT_AGENT_MODEL,
            "reasoning_effort": (
                config.agent.reasoning_effort or DEFAULT_AGENT_REASONING_EFFORT
            ),
        },
        "codex": {
            "sandbox": config.codex.sandbox or "workspace-write",
            "timeout_seconds": config.codex.timeout_seconds,
        },
        "loops": [_loop_config_to_raw(loop) for loop in config.loops],
        "notifications": {
            "policy": config.notifications.policy,
        },
    }


def _loop_config_to_raw(loop: RuntimeLoopConfig) -> dict[str, Any]:
    """把 RuntimeLoopConfig 规范化为 JSON 可序列化对象。"""
    return {
        "id": loop.id,
        "enabled": loop.enabled,
        "interval_seconds": loop.interval_seconds,
        "prompt": loop.prompt,
        "skill_names": list(loop.skill_names),
        "sink_mode": loop.sink_mode,
        "notify_policy": loop.notify_policy,
        "default_channel": loop.default_channel,
        "default_target_type": loop.default_target_type,
        "default_target_id": loop.default_target_id,
        "prevent_overlap": loop.prevent_overlap,
        "max_concurrent_runs": loop.max_concurrent_runs,
    }


def _section(raw: Mapping[str, Any], key: str) -> dict[str, Any]:
    """读取 runtime config section，并确保它是对象。"""
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise RuntimeError(f"runtime config section {key} must be an object")
    return value


def _required_str(section: Mapping[str, Any], key: str) -> str:
    """读取必填字符串字段，不合法时抛出 RuntimeError。"""
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"runtime config value {key} is required")
    return value.strip()


def _optional_str(section: Mapping[str, Any], key: str) -> str | None:
    """读取可选字符串字段，并把空白字符串归一为空值。"""
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"runtime config value {key} must be a string")
    value = value.strip()
    return value or None


def _optional_int(section: Mapping[str, Any], key: str) -> int | None:
    """读取可选整数字段。"""
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise RuntimeError(f"runtime config value {key} must be an integer")
    return value


def _positive_int_or_default(
    section: Mapping[str, Any],
    key: str,
    *,
    default: int,
) -> int:
    """读取正整数字段，缺省时使用默认值。"""
    value = _optional_int(section, key)
    if value is None:
        return default
    if value < 1:
        raise RuntimeError(f"runtime config value {key} must be >= 1")
    return value


def _optional_bool(section: Mapping[str, Any], key: str, *, default: bool) -> bool:
    """读取布尔字段，不合法时抛出 RuntimeError。"""
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise RuntimeError(f"runtime config value {key} must be a boolean")
    return value


def _optional_str_tuple(section: Mapping[str, Any], key: str) -> tuple[str, ...]:
    """读取字符串数组并转换成 tuple。"""
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


def _validate_loop_id_value(value: str) -> str:
    """校验 loop_id 字符串非空。"""
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("loop_id is required")
    return value.strip()


def _object_list(raw: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    """读取对象数组并返回深拷贝，避免原对象被修改。"""
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise RuntimeError(f"runtime config value {key} must be an array")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise RuntimeError(f"runtime config value {key} must be an object array")
        result.append(copy.deepcopy(item))
    return result


def _deep_merge(base: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    """递归深度合并 JSON-like mapping。"""
    result = copy.deepcopy(dict(base))
    for key, value in patch.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _loop_update_summary(
    action: str,
    loop_id: str,
    updates: Mapping[str, Any],
) -> str:
    """生成 loop 更新操作的简短审计摘要。"""
    changed_keys = sorted(str(key) for key in updates.keys() if key != "id")
    if action == "enable_loop":
        return f"enable loop {loop_id}"
    if action == "disable_loop":
        return f"disable loop {loop_id}"
    return f"update loop {loop_id} keys={','.join(changed_keys) or 'none'}"


def _json_text(data: Mapping[str, Any]) -> str:
    """用稳定缩进格式序列化 JSON 文本。"""
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _hash_file(path: Path) -> str | None:
    """计算文件 SHA-256，不存在时返回 None。"""
    if not path.exists():
        return None
    return _hash_bytes(path.read_bytes())


def _hash_bytes(data: bytes) -> str:
    """计算字节串 SHA-256。"""
    return hashlib.sha256(data).hexdigest()


def _fsync_directory(path: Path) -> None:
    """fsync 目录项，尽量保证 rename 持久化。"""
    if not hasattr(os, "O_DIRECTORY"):
        return
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
