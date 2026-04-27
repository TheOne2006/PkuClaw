from __future__ import annotations

from pathlib import Path


BASE_SKILL_NAMES = ("runtime/codex-subagent.md",)

SKILL_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "tasks/write-notes.md": (
        "tools/pdf-reader.md",
    ),
    "tasks/do-homework.md": (
        "tools/pdf-reader.md",
        "tools/pku3b-setup.md",
    ),
    "tasks/sync-notices.md": (
        "tools/pku3b-setup.md",
        "tools/data-parser.md",
    ),
}


def render_subskills(
    names: tuple[str, ...],
    *,
    skills_dir: Path,
) -> str:
    blocks: list[str] = []
    for name in resolve_subskill_names(names):
        path = _skill_path(skills_dir, name)
        content = path.read_text(encoding="utf-8").strip()
        blocks.append(f"## {name}\n\n{content}")
    return "\n\n---\n\n".join(blocks)


def resolve_subskill_names(names: tuple[str, ...]) -> tuple[str, ...]:
    resolved: list[str] = []
    seen: set[str] = set()
    for name in (*BASE_SKILL_NAMES, *names):
        _append_skill(name, resolved, seen)
        for dependency in SKILL_DEPENDENCIES.get(name, ()):
            _append_skill(dependency, resolved, seen)
    return tuple(resolved)


def _append_skill(name: str, resolved: list[str], seen: set[str]) -> None:
    normalized = name.strip().lstrip("/")
    if not normalized or normalized in seen:
        return
    resolved.append(normalized)
    seen.add(normalized)


def _skill_path(skills_dir: Path, name: str) -> Path:
    path = (skills_dir / name).resolve()
    root = skills_dir.resolve()
    if root not in path.parents:
        raise ValueError(f"sub-skill escapes skill root: {name}")
    if not path.is_file():
        raise FileNotFoundError(f"sub-skill not found: {name}")
    return path
