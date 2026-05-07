"""Hot-load Agent prompt templates from configs/runtime/prompts.json."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


RUNTIME_PROMPTS_FILE = "prompts.json"
SUPPORTED_PROMPTS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RuntimePromptTemplate:
    """One prompt template loaded from runtime config."""

    template: str
    suggested_skills_template: str = ""


@dataclass(frozen=True)
class RuntimePromptTemplates:
    """Prompt templates for the two supported Agent run sources."""

    schema_version: int
    realtime: RuntimePromptTemplate
    loop: RuntimePromptTemplate
    path: Path


def read_prompt_templates(config_dir: Path) -> RuntimePromptTemplates:
    """Read and validate prompts.json for every prompt build."""

    path = config_dir / RUNTIME_PROMPTS_FILE
    if not path.exists():
        raise FileNotFoundError(f"runtime prompts file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("runtime prompts file must be a JSON object")
    return _parse_templates(raw, path=path)


def render_prompt_template(template: str, variables: Mapping[str, Any]) -> str:
    """Render one runtime prompt template with strict variable substitution."""

    try:
        return template.format(**{key: str(value) for key, value in variables.items()})
    except KeyError as exc:
        missing = str(exc).strip("'")
        raise RuntimeError(f"runtime prompt template references unknown variable: {missing}") from exc


def _parse_templates(raw: Mapping[str, Any], *, path: Path) -> RuntimePromptTemplates:
    schema_version = _schema_version(raw)
    return RuntimePromptTemplates(
        schema_version=schema_version,
        realtime=_parse_template_section(raw, "realtime"),
        loop=_parse_template_section(raw, "loop"),
        path=path,
    )


def _schema_version(raw: Mapping[str, Any]) -> int:
    value = raw.get("schema_version")
    if not isinstance(value, int):
        raise RuntimeError("runtime prompts value schema_version must be an integer")
    if value != SUPPORTED_PROMPTS_SCHEMA_VERSION:
        raise RuntimeError(
            "unsupported runtime prompts schema_version: "
            f"{value} (supported: {SUPPORTED_PROMPTS_SCHEMA_VERSION})"
        )
    return value


def _parse_template_section(raw: Mapping[str, Any], key: str) -> RuntimePromptTemplate:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        raise RuntimeError(f"runtime prompts section {key} must be an object")
    template = value.get("template")
    if not isinstance(template, str) or not template.strip():
        raise RuntimeError(f"runtime prompts section {key}.template is required")
    suggested_skills_template = value.get("suggested_skills_template", "")
    if key == "realtime" and (
        not isinstance(suggested_skills_template, str)
        or not suggested_skills_template.strip()
    ):
        raise RuntimeError(
            "runtime prompts section realtime.suggested_skills_template is required"
        )
    if not isinstance(suggested_skills_template, str):
        raise RuntimeError(
            f"runtime prompts section {key}.suggested_skills_template must be a string"
        )
    return RuntimePromptTemplate(
        template=template,
        suggested_skills_template=suggested_skills_template,
    )
