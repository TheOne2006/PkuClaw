from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    instructions: str
    confirmation_required: bool = False


CAPABILITIES: dict[str, Capability] = {
    "resident": Capability(
        name="resident",
        description="Operate as the reasoning worker behind PkuClaw's core loop.",
        instructions=(
            "You are invoked by PkuClaw backend code, not directly by the chat "
            "user. Keep responses concise, mention produced artifacts, and ask a "
            "clear question if user input is required."
        ),
    ),
    "course.snapshot.read": Capability(
        name="course.snapshot.read",
        description="Use local teaching-network snapshots prepared by the backbone.",
        instructions=(
            "Prefer local state, artifacts, and snapshots over live network access. "
            "If a requested snapshot is missing, say which data source the backend "
            "needs to collect."
        ),
    ),
    "notes.write": Capability(
        name="notes.write",
        description="Draft or continue course notes from local materials.",
        instructions=(
            "Create structured notes in the run directory. Preserve source names "
            "and clearly separate facts from your interpretation."
        ),
    ),
    "homework.plan": Capability(
        name="homework.plan",
        description="Plan homework work without submitting it.",
        instructions=(
            "Plan steps, inspect local attachments if present, and prepare drafts. "
            "Do not submit homework or claim submission."
        ),
    ),
    "homework.submit": Capability(
        name="homework.submit",
        description="Submit homework through the backend after explicit approval.",
        instructions=(
            "Submission requires an explicit backend confirmation flag. If it is "
            "not present, stop at a dry-run plan."
        ),
        confirmation_required=True,
    ),
    "notice.summarize": Capability(
        name="notice.summarize",
        description="Summarize assignments, announcements, and deadlines.",
        instructions=(
            "Summarize by urgency first, include dates when available, and keep "
            "uncertain items marked as uncertain."
        ),
    ),
}


BASE_CAPABILITY_NAMES = ("resident", "course.snapshot.read")


def select_capabilities(names: tuple[str, ...]) -> list[Capability]:
    selected: list[Capability] = []
    seen: set[str] = set()
    for name in (*BASE_CAPABILITY_NAMES, *names):
        if name in seen:
            continue
        selected.append(CAPABILITIES[name])
        seen.add(name)
    return selected


def render_capabilities(names: tuple[str, ...]) -> str:
    blocks: list[str] = []
    for capability in select_capabilities(names):
        confirm = "yes" if capability.confirmation_required else "no"
        blocks.append(
            "\n".join(
                [
                    f"### {capability.name}",
                    f"- Description: {capability.description}",
                    f"- Requires confirmation: {confirm}",
                    f"- Instructions: {capability.instructions}",
                ]
            )
        )
    return "\n\n".join(blocks)
