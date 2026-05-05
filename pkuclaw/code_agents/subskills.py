from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping


BASE_SKILL_NAMES = ("runtime/codex-subagent.md",)
SKILL_REGISTRY_FILE = "skills.json"
SUPPORTED_SKILL_REGISTRY_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SkillSpec:
    name: str
    intent: str
    dependencies: tuple[str, ...] = ()
    allowed_sources: tuple[str, ...] = ()
    requires_confirmation: bool = False


@dataclass(frozen=True)
class SkillRegistry:
    """Hot-loaded registry for prompt-injected PkuClaw skills."""

    schema_version: int
    skills: Mapping[str, SkillSpec]
    path: Path | None = None
    warnings: tuple[str, ...] = ()
    using_default: bool = False

    def spec_for(self, name: str) -> SkillSpec | None:
        return self.skills.get(normalize_skill_name(name))

    def skill_for_intent(
        self,
        intent: str,
        *,
        source: str | None = None,
    ) -> SkillSpec | None:
        normalized_intent = intent.strip()
        if not normalized_intent:
            return None
        for spec in self.skills.values():
            if spec.intent != normalized_intent:
                continue
            if source is not None and source not in spec.allowed_sources:
                continue
            return spec
        return None


_DEFAULT_ALLOWED_SOURCES = (
    "realtime",
    "loop",
    "mcp",
    "manual",
    "system",
)

_IMMUTABLE_DEFAULT_SKILL_SPECS = (
    SkillSpec(
        name="runtime/codex-subagent.md",
        intent="runtime",
        allowed_sources=_DEFAULT_ALLOWED_SOURCES,
    ),
    SkillSpec(
        name="tasks/write-notes.md",
        intent="notes",
        dependencies=("tools/pdf-reader.md",),
        allowed_sources=("realtime", "loop"),
        requires_confirmation=False,
    ),
    SkillSpec(
        name="tasks/do-homework.md",
        intent="homework",
        dependencies=("tools/pdf-reader.md", "tools/pku3b-setup.md"),
        allowed_sources=("realtime",),
        requires_confirmation=True,
    ),
    SkillSpec(
        name="tasks/sync-notices.md",
        intent="sync",
        dependencies=("tools/pku3b-setup.md", "tools/data-parser.md"),
        allowed_sources=("realtime", "loop"),
        requires_confirmation=False,
    ),
    SkillSpec(
        name="tools/pdf-reader.md",
        intent="tool",
        allowed_sources=_DEFAULT_ALLOWED_SOURCES,
    ),
    SkillSpec(
        name="tools/pku3b-setup.md",
        intent="tool",
        allowed_sources=_DEFAULT_ALLOWED_SOURCES,
    ),
    SkillSpec(
        name="tools/data-parser.md",
        intent="tool",
        allowed_sources=_DEFAULT_ALLOWED_SOURCES,
    ),
)


def load_skill_registry(
    registry_path: Path | None = None,
    *,
    skills_dir: Path | None = None,
) -> SkillRegistry:
    """Load skills.json, falling back to an immutable built-in registry."""

    resolved_path = _default_registry_path(skills_dir) if registry_path is None else registry_path
    if resolved_path is None:
        return _default_registry()
    try:
        if not resolved_path.exists():
            raise FileNotFoundError(f"skill registry not found: {resolved_path}")
        raw = json.loads(resolved_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError("skill registry must be a JSON object")
        return _parse_registry(raw, path=resolved_path, skills_dir=skills_dir)
    except Exception as exc:
        return _default_registry(
            path=resolved_path,
            warning=f"skill registry fallback: {exc}",
            skills_dir=skills_dir,
        )


def render_subskills(
    names: tuple[str, ...],
    *,
    skills_dir: Path,
    registry: SkillRegistry | None = None,
    registry_path: Path | None = None,
    source: str | None = None,
) -> str:
    registry = registry or load_skill_registry(
        registry_path,
        skills_dir=skills_dir,
    )
    blocks: list[str] = []
    for name in resolve_subskill_names(
        names,
        registry=registry,
        skills_dir=skills_dir,
        source=source,
    ):
        path = _skill_path(skills_dir, name)
        content = path.read_text(encoding="utf-8").strip()
        metadata = _render_skill_metadata(registry.spec_for(name))
        if metadata:
            blocks.append(f"## {name}\n\n{metadata}\n\n{content}")
        else:
            blocks.append(f"## {name}\n\n{content}")
    return "\n\n---\n\n".join(blocks)


def resolve_subskill_names(
    names: tuple[str, ...],
    *,
    registry: SkillRegistry | None = None,
    registry_path: Path | None = None,
    skills_dir: Path | None = None,
    source: str | None = None,
) -> tuple[str, ...]:
    registry = registry or load_skill_registry(
        registry_path,
        skills_dir=skills_dir,
    )
    resolved: list[str] = []
    seen: set[str] = set()
    requested: list[str] = []
    for name in BASE_SKILL_NAMES:
        normalized = normalize_skill_name(name)
        _validate_skill_reference(
            normalized,
            registry=registry,
            skills_dir=skills_dir,
            source=None,
        )
        _append_skill(normalized, resolved, seen)
    for name in names:
        normalized = normalize_skill_name(name)
        _validate_skill_reference(
            normalized,
            registry=registry,
            skills_dir=skills_dir,
            source=source,
        )
        requested.append(normalized)
        _append_skill(normalized, resolved, seen)
    for name in requested:
        _append_dependencies(
            name,
            registry=registry,
            skills_dir=skills_dir,
            source=source,
            resolved=resolved,
            seen=seen,
            stack=(),
        )
    return tuple(resolved)


def normalize_skill_name(name: str) -> str:
    if not isinstance(name, str):
        raise RuntimeError("skill path must be a string")
    raw = name.strip()
    if not raw:
        raise RuntimeError("skill path is required")
    path = PurePosixPath(raw)
    if path.is_absolute():
        raise RuntimeError(f"skill path must be relative: {name}")
    if any(part == ".." for part in path.parts):
        raise RuntimeError(f"skill path escapes skill root: {name}")
    normalized = path.as_posix()
    if normalized in {"", "."}:
        raise RuntimeError("skill path is required")
    if not normalized.endswith(".md"):
        raise RuntimeError(f"skill path must point to a markdown file: {name}")
    return normalized


def _append_dependencies(
    name: str,
    *,
    registry: SkillRegistry,
    skills_dir: Path | None,
    source: str | None,
    resolved: list[str],
    seen: set[str],
    stack: tuple[str, ...],
) -> None:
    if name in stack:
        cycle = " -> ".join((*stack, name))
        raise RuntimeError(f"skill dependency cycle: {cycle}")
    spec = registry.spec_for(name)
    if spec is None:
        return
    for dependency in spec.dependencies:
        _validate_skill_reference(
            dependency,
            registry=registry,
            skills_dir=skills_dir,
            source=source,
        )
        _append_skill(dependency, resolved, seen)
        _append_dependencies(
            dependency,
            registry=registry,
            skills_dir=skills_dir,
            source=source,
            resolved=resolved,
            seen=seen,
            stack=(*stack, name),
        )


def _append_skill(name: str, resolved: list[str], seen: set[str]) -> None:
    normalized = normalize_skill_name(name)
    if not normalized or normalized in seen:
        return
    resolved.append(normalized)
    seen.add(normalized)


def _skill_path(skills_dir: Path, name: str) -> Path:
    normalized = normalize_skill_name(name)
    path = (skills_dir / normalized).resolve()
    root = skills_dir.resolve()
    if root not in path.parents:
        raise ValueError(f"sub-skill escapes skill root: {name}")
    if not path.is_file():
        raise FileNotFoundError(f"sub-skill not found: {name}")
    return path


def _default_registry_path(skills_dir: Path | None) -> Path | None:
    if skills_dir is None:
        return None
    return skills_dir.resolve().parent / "configs" / "runtime" / SKILL_REGISTRY_FILE


def _default_registry(
    *,
    path: Path | None = None,
    warning: str | None = None,
    skills_dir: Path | None = None,
) -> SkillRegistry:
    specs = tuple(_IMMUTABLE_DEFAULT_SKILL_SPECS)
    _validate_registry_specs(specs, skills_dir=skills_dir)
    warnings = (warning,) if warning else ()
    return SkillRegistry(
        schema_version=SUPPORTED_SKILL_REGISTRY_SCHEMA_VERSION,
        skills=MappingProxyType({spec.name: spec for spec in specs}),
        path=path,
        warnings=warnings,
        using_default=True,
    )


def _parse_registry(
    raw: Mapping[str, Any],
    *,
    path: Path,
    skills_dir: Path | None,
) -> SkillRegistry:
    schema_version = _schema_version(raw)
    raw_skills = raw.get("skills")
    if not isinstance(raw_skills, list):
        raise RuntimeError("skill registry value skills must be an array")
    specs: list[SkillSpec] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_skills):
        if not isinstance(item, Mapping):
            raise RuntimeError("skill registry value skills must be an object array")
        spec = _parse_skill_spec(item, index=index)
        if spec.name in seen:
            raise RuntimeError(f"duplicate skill registry entry: {spec.name}")
        seen.add(spec.name)
        specs.append(spec)
    _validate_registry_specs(tuple(specs), skills_dir=skills_dir)
    return SkillRegistry(
        schema_version=schema_version,
        skills=MappingProxyType({spec.name: spec for spec in specs}),
        path=path,
        using_default=False,
    )


def _parse_skill_spec(item: Mapping[str, Any], *, index: int) -> SkillSpec:
    name = normalize_skill_name(_required_str(item, "name"))
    dependencies = tuple(
        normalize_skill_name(value)
        for value in _optional_str_list(item, "dependencies")
    )
    return SkillSpec(
        name=name,
        intent=_optional_str(item, "intent") or "",
        dependencies=dependencies,
        allowed_sources=_allowed_sources(item),
        requires_confirmation=_optional_bool(
            item,
            "requires_confirmation",
            default=False,
        ),
    )


def _schema_version(raw: Mapping[str, Any]) -> int:
    value = raw.get("schema_version", SUPPORTED_SKILL_REGISTRY_SCHEMA_VERSION)
    if not isinstance(value, int):
        raise RuntimeError("skill registry value schema_version must be an integer")
    if value != SUPPORTED_SKILL_REGISTRY_SCHEMA_VERSION:
        raise RuntimeError(
            "unsupported skill registry schema_version: "
            f"{value} (supported: {SUPPORTED_SKILL_REGISTRY_SCHEMA_VERSION})"
        )
    return value


def _validate_registry_specs(
    specs: tuple[SkillSpec, ...],
    *,
    skills_dir: Path | None,
) -> None:
    by_name = {spec.name: spec for spec in specs}
    if len(by_name) != len(specs):
        raise RuntimeError("duplicate skill registry entry")
    for spec in specs:
        if skills_dir is not None:
            _skill_path(skills_dir, spec.name)
        for dependency in spec.dependencies:
            normalize_skill_name(dependency)
            if skills_dir is not None:
                _skill_path(skills_dir, dependency)
    _validate_dependency_cycles(by_name)


def _validate_dependency_cycles(registry: Mapping[str, SkillSpec]) -> None:
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(name: str, stack: tuple[str, ...]) -> None:
        if name in visited:
            return
        if name in visiting:
            cycle = " -> ".join((*stack, name))
            raise RuntimeError(f"skill dependency cycle: {cycle}")
        visiting.add(name)
        spec = registry.get(name)
        if spec is not None:
            for dependency in spec.dependencies:
                if dependency in registry:
                    visit(dependency, (*stack, name))
        visiting.remove(name)
        visited.add(name)

    for name in registry:
        visit(name, ())


def _validate_skill_reference(
    name: str,
    *,
    registry: SkillRegistry,
    skills_dir: Path | None,
    source: str | None,
) -> None:
    normalized = normalize_skill_name(name)
    if skills_dir is not None:
        _skill_path(skills_dir, normalized)
    spec = registry.spec_for(normalized)
    if source is None or spec is None:
        return
    if source not in spec.allowed_sources:
        raise RuntimeError(
            f"skill {normalized} is not allowed for source {source}; "
            f"allowed sources: {', '.join(spec.allowed_sources) or 'none'}"
        )


def _render_skill_metadata(spec: SkillSpec | None) -> str:
    if spec is None:
        return ""
    dependencies = ", ".join(spec.dependencies) or "none"
    allowed_sources = ", ".join(spec.allowed_sources) or "none"
    requires_confirmation = "true" if spec.requires_confirmation else "false"
    intent = spec.intent or "none"
    return (
        "Metadata: "
        f"intent=`{intent}`; "
        f"allowed_sources=`{allowed_sources}`; "
        f"requires_confirmation=`{requires_confirmation}`; "
        f"dependencies=`{dependencies}`."
    )


def _required_str(item: Mapping[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"skill registry value {key} is required")
    return value.strip()


def _optional_str(item: Mapping[str, Any], key: str) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"skill registry value {key} must be a string")
    value = value.strip()
    return value or None


def _optional_str_list(item: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = item.get(key, [])
    if not isinstance(value, list):
        raise RuntimeError(f"skill registry value {key} must be a string array")
    result: list[str] = []
    for raw_item in value:
        if not isinstance(raw_item, str):
            raise RuntimeError(f"skill registry value {key} must be a string array")
        stripped = raw_item.strip()
        if stripped:
            result.append(stripped)
    return tuple(result)


def _allowed_sources(item: Mapping[str, Any]) -> tuple[str, ...]:
    sources = _optional_str_list(item, "allowed_sources")
    if not sources:
        return _DEFAULT_ALLOWED_SOURCES
    normalized: list[str] = []
    seen: set[str] = set()
    for source in sources:
        value = source.strip()
        if not value:
            continue
        if value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return tuple(normalized) or _DEFAULT_ALLOWED_SOURCES


def _optional_bool(
    item: Mapping[str, Any],
    key: str,
    *,
    default: bool,
) -> bool:
    value = item.get(key, default)
    if not isinstance(value, bool):
        raise RuntimeError(f"skill registry value {key} must be a boolean")
    return value
