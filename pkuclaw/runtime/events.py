"""Hot-load runtime realtime quick actions from configs/runtime/events.json."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from pkuclaw.runtime.skills import normalize_skill_name


RUNTIME_EVENTS_FILE = "events.json"
SUPPORTED_EVENTS_SCHEMA_VERSION = 1
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


@dataclass(frozen=True)
class RuntimeEventSpec:
    """One user-triggered realtime quick action."""

    id: str
    title: str
    description: str
    task: str
    skill_names: tuple[str, ...] = ()
    ack: str = "收到，我开始处理。"
    enabled: bool = True


@dataclass(frozen=True)
class RuntimeEventCatalog:
    """Hot-loaded quick action catalog plus optional channel key mappings."""

    schema_version: int
    events: Mapping[str, RuntimeEventSpec]
    channel_mappings: Mapping[str, Mapping[str, str]]
    path: Path | None = None
    warnings: tuple[str, ...] = ()

    def spec_for(self, event_id: str) -> RuntimeEventSpec | None:
        """Return an enabled event spec by PkuClaw event id."""

        normalized = normalize_event_id(event_id)
        spec = self.events.get(normalized)
        if spec is None or not spec.enabled:
            return None
        return spec

    def resolve_channel_event_id(self, *, channel: str, raw_event_id: str) -> str | None:
        """Map a raw channel action key to a PkuClaw event id, or pass through known ids."""

        raw = str(raw_event_id or "").strip()
        if not raw:
            return None
        mapping = self.channel_mappings.get(str(channel or "").strip(), {})
        mapped = mapping.get(raw)
        if mapped:
            return mapped if self.spec_for(mapped) is not None else None
        # No conversion is needed when the channel key is already a PkuClaw event id.
        try:
            normalized = normalize_event_id(raw)
        except RuntimeError:
            return None
        return normalized if self.spec_for(normalized) is not None else None


def read_event_catalog(config_dir: Path) -> RuntimeEventCatalog:
    """Read events.json; return an empty warned catalog if missing or broken."""

    path = config_dir / RUNTIME_EVENTS_FILE
    try:
        if not path.exists():
            raise FileNotFoundError(f"runtime events file not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError("runtime events file must be a JSON object")
        return _parse_catalog(raw, path=path)
    except Exception as exc:
        return RuntimeEventCatalog(
            schema_version=SUPPORTED_EVENTS_SCHEMA_VERSION,
            events=MappingProxyType({}),
            channel_mappings=MappingProxyType({}),
            path=path,
            warnings=(f"runtime events unavailable: {exc}",),
        )


def resolve_channel_event_id(
    *,
    config_dir: Path,
    channel: str,
    raw_event_id: str,
) -> str | None:
    """Resolve one channel raw action key through the runtime event catalog."""

    return read_event_catalog(config_dir).resolve_channel_event_id(
        channel=channel,
        raw_event_id=raw_event_id,
    )


def normalize_event_id(value: str) -> str:
    """Validate and normalize a PkuClaw quick action event id."""

    if not isinstance(value, str):
        raise RuntimeError("runtime event id must be a string")
    normalized = value.strip()
    if not normalized:
        raise RuntimeError("runtime event id is required")
    if not _EVENT_ID_RE.match(normalized):
        raise RuntimeError(f"invalid runtime event id: {value}")
    return normalized


def _parse_catalog(raw: Mapping[str, Any], *, path: Path) -> RuntimeEventCatalog:
    schema_version = _schema_version(raw)
    raw_events = raw.get("events")
    if not isinstance(raw_events, list):
        raise RuntimeError("runtime events value events must be an array")
    events: dict[str, RuntimeEventSpec] = {}
    for index, item in enumerate(raw_events):
        if not isinstance(item, Mapping):
            raise RuntimeError("runtime events value events must be an object array")
        spec = _parse_event(item, index=index)
        if spec.id in events:
            raise RuntimeError(f"duplicate runtime event id: {spec.id}")
        events[spec.id] = spec
    channel_mappings = _parse_channel_mappings(raw.get("channel_mappings", {}), events)
    return RuntimeEventCatalog(
        schema_version=schema_version,
        events=MappingProxyType(events),
        channel_mappings=MappingProxyType(
            {channel: MappingProxyType(mapping) for channel, mapping in channel_mappings.items()}
        ),
        path=path,
    )


def _parse_event(item: Mapping[str, Any], *, index: int) -> RuntimeEventSpec:
    event_id = normalize_event_id(_required_str(item, "id"))
    task = _required_str(item, "task")
    skill_names = tuple(normalize_skill_name(name) for name in _optional_str_list(item, "skill_names"))
    return RuntimeEventSpec(
        id=event_id,
        title=_optional_str(item, "title") or event_id,
        description=_optional_str(item, "description") or "",
        task=task,
        skill_names=skill_names,
        ack=_optional_str(item, "ack") or "收到，我开始处理。",
        enabled=_optional_bool(item, "enabled", default=True),
    )


def _parse_channel_mappings(
    raw: Any,
    events: Mapping[str, RuntimeEventSpec],
) -> dict[str, dict[str, str]]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise RuntimeError("runtime events value channel_mappings must be an object")
    parsed: dict[str, dict[str, str]] = {}
    for raw_channel, raw_mapping in raw.items():
        if not isinstance(raw_channel, str) or not raw_channel.strip():
            raise RuntimeError("runtime events channel_mappings keys must be strings")
        if not isinstance(raw_mapping, Mapping):
            raise RuntimeError("runtime events channel mapping must be an object")
        channel = raw_channel.strip()
        parsed[channel] = {}
        for raw_key, raw_event_id in raw_mapping.items():
            if not isinstance(raw_key, str) or not raw_key.strip():
                raise RuntimeError("runtime events channel event keys must be strings")
            event_id = normalize_event_id(_string_value(raw_event_id, "channel mapped event id"))
            if event_id not in events:
                raise RuntimeError(f"channel mapping points to unknown runtime event: {event_id}")
            parsed[channel][raw_key.strip()] = event_id
    return parsed


def _schema_version(raw: Mapping[str, Any]) -> int:
    value = raw.get("schema_version", SUPPORTED_EVENTS_SCHEMA_VERSION)
    if not isinstance(value, int):
        raise RuntimeError("runtime events value schema_version must be an integer")
    if value != SUPPORTED_EVENTS_SCHEMA_VERSION:
        raise RuntimeError(
            "unsupported runtime events schema_version: "
            f"{value} (supported: {SUPPORTED_EVENTS_SCHEMA_VERSION})"
        )
    return value


def _required_str(item: Mapping[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"runtime events value {key} is required")
    return value.strip()


def _optional_str(item: Mapping[str, Any], key: str) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"runtime events value {key} must be a string")
    value = value.strip()
    return value or None


def _optional_str_list(item: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = item.get(key, [])
    if not isinstance(value, list):
        raise RuntimeError(f"runtime events value {key} must be a string array")
    result: list[str] = []
    for raw_item in value:
        if not isinstance(raw_item, str):
            raise RuntimeError(f"runtime events value {key} must be a string array")
        stripped = raw_item.strip()
        if stripped:
            result.append(stripped)
    return tuple(result)


def _optional_bool(item: Mapping[str, Any], key: str, *, default: bool) -> bool:
    value = item.get(key, default)
    if not isinstance(value, bool):
        raise RuntimeError(f"runtime events value {key} must be a boolean")
    return value


def _string_value(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"runtime events {label} must be a string")
    return value.strip()
