"""Hot-load PkuClaw runtime skill catalog from configs/runtime/skills.json."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping


BASE_SKILL_NAMES: tuple[str, ...] = ()
NOTIFICATION_SKILL_NAME = "tools/channel-notifier.md"
SKILL_REGISTRY_FILE = "skills.json"
SUPPORTED_SKILL_REGISTRY_SCHEMA_VERSION = 1
ALLOWED_RUN_SOURCES = ("realtime", "loop")


@dataclass(frozen=True)
class SkillSpec:
    """Declarative metadata for one runtime skill."""

    name: str
    path: str
    description: str = ""
    dependencies: tuple[str, ...] = ()
    allowed_sources: tuple[str, ...] = ALLOWED_RUN_SOURCES
    requires_confirmation: bool = False


@dataclass(frozen=True)
class SkillRegistry:
    """Hot-loaded registry for runtime skills."""

    schema_version: int
    skills: Mapping[str, SkillSpec]
    path: Path | None = None
    warnings: tuple[str, ...] = ()

    def spec_for(self, ref: str) -> SkillSpec | None:
        """Find a skill by catalog name or by normalized markdown path."""

        if not isinstance(ref, str):
            return None
        raw = ref.strip()
        if not raw:
            return None
        spec = self.skills.get(raw)
        if spec is not None:
            return spec
        try:
            normalized_path = normalize_skill_name(raw)
        except RuntimeError:
            return None
        for candidate in self.skills.values():
            if candidate.path == normalized_path:
                return candidate
        return None


_EMPTY_REGISTRY = SkillRegistry(
    schema_version=SUPPORTED_SKILL_REGISTRY_SCHEMA_VERSION,
    skills=MappingProxyType({}),
)


def load_skill_registry(
    registry_path: Path | None = None,
    *,
    skills_dir: Path | None = None,
) -> SkillRegistry:
    """Load skills.json; return an empty warned catalog if it is missing/broken."""

    resolved_path = _default_registry_path(skills_dir) if registry_path is None else registry_path
    if resolved_path is None:
        return _empty_registry(warning="skill registry path is not configured")
    try:
        if not resolved_path.exists():
            raise FileNotFoundError(f"skill registry not found: {resolved_path}")
        raw = json.loads(resolved_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError("skill registry must be a JSON object")
        return _parse_registry(raw, path=resolved_path, skills_dir=skills_dir)
    except Exception as exc:
        return _empty_registry(
            path=resolved_path,
            warning=f"skill registry unavailable: {exc}",
        )


def render_skill_catalog(
    *,
    registry: SkillRegistry,
    skills_dir: Path,
    source: str | None = None,
) -> str:
    """Render a compact catalog for Agents to choose and read skill files."""

    lines: list[str] = []
    if registry.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in registry.warnings)
        lines.append("")
    lines.append("Available skills:")
    rendered_any = False
    for spec in registry.skills.values():
        if source is not None and source not in spec.allowed_sources:
            continue
        rendered_any = True
        lines.extend(_render_skill_spec_lines(spec, skills_dir=skills_dir))
    if not rendered_any:
        lines.append("- none")
    return "\n".join(lines)


def render_suggested_skills(
    names: tuple[str, ...],
    *,
    skills_dir: Path,
    registry: SkillRegistry,
    source: str | None = None,
) -> str:
    """Render suggested skill metadata without injecting markdown bodies."""

    if not names:
        return "- none"
    lines = ["Suggested skills for this run (read them by path if useful):"]
    rendered_any = False
    try:
        resolved = resolve_subskill_names(
            names,
            registry=registry,
            skills_dir=skills_dir,
            source=source,
        )
    except Exception as exc:
        return f"- failed to resolve suggested skills: {exc}"
    for skill_path in resolved:
        spec = registry.spec_for(skill_path) or SkillSpec(
            name=skill_path,
            path=skill_path,
            description="No catalog description provided.",
        )
        rendered_any = True
        lines.extend(_render_skill_spec_lines(spec, skills_dir=skills_dir))
    if not rendered_any:
        lines.append("- none")
    return "\n".join(lines)


def render_subskills(
    names: tuple[str, ...],
    *,
    skills_dir: Path,
    registry: SkillRegistry | None = None,
    registry_path: Path | None = None,
    source: str | None = None,
) -> str:
    """Resolve skill dependencies and concatenate markdown bodies for explicit callers."""

    registry = registry or load_skill_registry(
        registry_path,
        skills_dir=skills_dir,
    )
    blocks: list[str] = []
    for skill_path in resolve_subskill_names(
        names,
        registry=registry,
        skills_dir=skills_dir,
        source=source,
    ):
        path = _skill_path(skills_dir, skill_path)
        content = path.read_text(encoding="utf-8").strip()
        metadata = _render_skill_metadata(registry.spec_for(skill_path))
        if metadata:
            blocks.append(f"## {skill_path}\n\n{metadata}\n\n{content}")
        else:
            blocks.append(f"## {skill_path}\n\n{content}")
    return "\n\n---\n\n".join(blocks)


def resolve_subskill_names(
    names: tuple[str, ...],
    *,
    registry: SkillRegistry | None = None,
    registry_path: Path | None = None,
    skills_dir: Path | None = None,
    source: str | None = None,
) -> tuple[str, ...]:
    """Normalize explicit skill references and append dependencies."""

    registry = registry or load_skill_registry(
        registry_path,
        skills_dir=skills_dir,
    )
    resolved: list[str] = []
    seen: set[str] = set()
    requested: list[str] = []
    for name in names:
        skill_path = _skill_ref_path(name, registry=registry)
        _validate_skill_reference(
            skill_path,
            registry=registry,
            skills_dir=skills_dir,
            source=source,
        )
        requested.append(skill_path)
        _append_skill(skill_path, resolved, seen)
    for skill_path in requested:
        _append_dependencies(
            skill_path,
            registry=registry,
            skills_dir=skills_dir,
            source=source,
            resolved=resolved,
            seen=seen,
            stack=(),
        )
    return tuple(resolved)


def normalize_skill_name(name: str) -> str:
    """Validate a relative markdown path under the runtime skill root."""

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


def _empty_registry(
    *,
    path: Path | None = None,
    warning: str | None = None,
) -> SkillRegistry:
    warnings = (warning,) if warning else ()
    return SkillRegistry(
        schema_version=_EMPTY_REGISTRY.schema_version,
        skills=_EMPTY_REGISTRY.skills,
        path=path,
        warnings=warnings,
    )


def _parse_registry(
    raw: Mapping[str, Any],
    *,
    path: Path,
    skills_dir: Path | None,
) -> SkillRegistry:
    """Parse skills.json into an immutable SkillRegistry."""

    schema_version = _schema_version(raw)
    raw_skills = raw.get("skills")
    if not isinstance(raw_skills, list):
        raise RuntimeError("skill registry value skills must be an array")
    specs: list[SkillSpec] = []
    seen_names: set[str] = set()
    seen_paths: set[str] = set()
    for index, item in enumerate(raw_skills):
        if not isinstance(item, Mapping):
            raise RuntimeError("skill registry value skills must be an object array")
        spec = _parse_skill_spec(item, index=index)
        if spec.name in seen_names:
            raise RuntimeError(f"duplicate skill registry name: {spec.name}")
        if spec.path in seen_paths:
            raise RuntimeError(f"duplicate skill registry path: {spec.path}")
        seen_names.add(spec.name)
        seen_paths.add(spec.path)
        specs.append(spec)
    _validate_registry_specs(tuple(specs), skills_dir=skills_dir)
    return SkillRegistry(
        schema_version=schema_version,
        skills=MappingProxyType({spec.name: spec for spec in specs}),
        path=path,
    )


def _parse_skill_spec(item: Mapping[str, Any], *, index: int) -> SkillSpec:
    """Parse one skill spec from skills.json."""

    name = _required_str(item, "name")
    path = normalize_skill_name(_optional_str(item, "path") or name)
    dependencies = tuple(
        normalize_skill_name(value)
        for value in _optional_str_list(item, "dependencies")
    )
    return SkillSpec(
        name=name,
        path=path,
        description=_optional_str(item, "description") or "",
        dependencies=dependencies,
        allowed_sources=_allowed_sources(item),
        requires_confirmation=_optional_bool(
            item,
            "requires_confirmation",
            default=False,
        ),
    )


def _schema_version(raw: Mapping[str, Any]) -> int:
    """Read and validate registry schema_version."""

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
    """Validate skill files, dependencies and dependency cycles."""

    by_path = {spec.path: spec for spec in specs}
    if len(by_path) != len(specs):
        raise RuntimeError("duplicate skill registry path")
    for spec in specs:
        if skills_dir is not None:
            _skill_path(skills_dir, spec.path)
        for dependency in spec.dependencies:
            normalize_skill_name(dependency)
            if skills_dir is not None:
                _skill_path(skills_dir, dependency)
    _validate_dependency_cycles(by_path)


def _validate_dependency_cycles(registry: Mapping[str, SkillSpec]) -> None:
    """Detect cycles in the skill dependency graph."""

    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(path: str, stack: tuple[str, ...]) -> None:
        if path in visited:
            return
        if path in visiting:
            cycle = " -> ".join((*stack, path))
            raise RuntimeError(f"skill dependency cycle: {cycle}")
        visiting.add(path)
        spec = registry.get(path)
        if spec is not None:
            for dependency in spec.dependencies:
                if dependency in registry:
                    visit(dependency, (*stack, path))
        visiting.remove(path)
        visited.add(path)

    for path in registry:
        visit(path, ())


def _append_dependencies(
    skill_path: str,
    *,
    registry: SkillRegistry,
    skills_dir: Path | None,
    source: str | None,
    resolved: list[str],
    seen: set[str],
    stack: tuple[str, ...],
) -> None:
    """Append dependencies recursively while checking for cycles."""

    if skill_path in stack:
        cycle = " -> ".join((*stack, skill_path))
        raise RuntimeError(f"skill dependency cycle: {cycle}")
    spec = registry.spec_for(skill_path)
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
            stack=(*stack, skill_path),
        )


def _append_skill(skill_path: str, resolved: list[str], seen: set[str]) -> None:
    normalized = normalize_skill_name(skill_path)
    if normalized in seen:
        return
    resolved.append(normalized)
    seen.add(normalized)


def _skill_ref_path(ref: str, *, registry: SkillRegistry) -> str:
    spec = registry.spec_for(ref)
    if spec is not None:
        return spec.path
    return normalize_skill_name(ref)


def _skill_path(skills_dir: Path, name: str) -> Path:
    """Resolve a skill file path and prevent escaping skills_dir."""

    normalized = normalize_skill_name(name)
    root = skills_dir.resolve()
    path = (root / normalized).resolve()
    if root != path and root not in path.parents:
        raise ValueError(f"skill escapes skill root: {name}")
    if not path.is_file():
        raise FileNotFoundError(f"skill not found: {name}")
    return path


def _default_registry_path(skills_dir: Path | None) -> Path | None:
    if skills_dir is None:
        return None
    return skills_dir.resolve().parent / SKILL_REGISTRY_FILE


def _validate_skill_reference(
    skill_path: str,
    *,
    registry: SkillRegistry,
    skills_dir: Path | None,
    source: str | None,
) -> None:
    normalized = normalize_skill_name(skill_path)
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


def _render_skill_spec_lines(spec: SkillSpec, *, skills_dir: Path) -> list[str]:
    dependencies = ", ".join(spec.dependencies) or "none"
    allowed_sources = ", ".join(spec.allowed_sources) or "none"
    requires_confirmation = "true" if spec.requires_confirmation else "false"
    relative_path = f"configs/runtime/skills/{spec.path}"
    return [
        f"- name: `{spec.name}`",
        f"  description: {spec.description or 'No description provided.'}",
        f"  path: `{relative_path}`",
        f"  dependencies: `{dependencies}`",
        f"  allowed_sources: `{allowed_sources}`",
        f"  requires_confirmation: `{requires_confirmation}`",
    ]


def _render_skill_metadata(spec: SkillSpec | None) -> str:
    if spec is None:
        return ""
    dependencies = ", ".join(spec.dependencies) or "none"
    allowed_sources = ", ".join(spec.allowed_sources) or "none"
    requires_confirmation = "true" if spec.requires_confirmation else "false"
    description = spec.description or "none"
    return (
        "Metadata: "
        f"name=`{spec.name}`; "
        f"path=`{spec.path}`; "
        f"description=`{description}`; "
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
    sources = _optional_str_list(item, "allowed_sources") or ALLOWED_RUN_SOURCES
    normalized: list[str] = []
    seen: set[str] = set()
    for source in sources:
        value = source.strip()
        if value not in ALLOWED_RUN_SOURCES:
            raise RuntimeError(
                "skill registry value allowed_sources must contain only "
                f"{', '.join(ALLOWED_RUN_SOURCES)}"
            )
        if value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return tuple(normalized) or ALLOWED_RUN_SOURCES


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
