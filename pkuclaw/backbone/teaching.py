from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from pkuclaw.connectors.pku3b import Pku3b
from pkuclaw.core.store import utc_now


@dataclass(frozen=True)
class BackboneSnapshot:
    created_at: str
    assignments_raw: str
    announcements_raw: str
    course_table_raw: str
    path: Path


class TeachingBackbone:
    """Deterministic teaching-network collector.

    This layer is intentionally not agentic. It calls pku3b, stores raw
    snapshots, and leaves reasoning/summarization to core workers.
    """

    def __init__(self, *, pku3b: Pku3b, snapshot_dir: Path) -> None:
        self.pku3b = pku3b
        self.snapshot_dir = snapshot_dir

    def collect_snapshot(self) -> BackboneSnapshot:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        created_at = utc_now()
        stem = created_at.replace(":", "").replace("+", "_")
        path = self.snapshot_dir / f"{stem}.json"

        assignments = self.pku3b.run("a", "ls", "-a")
        announcements = self.pku3b.run("ann", "ls")
        course_table = self.pku3b.run("ct", "-r")

        snapshot = BackboneSnapshot(
            created_at=created_at,
            assignments_raw=_require_success("pku3b a ls -a", assignments),
            announcements_raw=_require_success("pku3b ann ls", announcements),
            course_table_raw=_require_success("pku3b ct -r", course_table),
            path=path,
        )
        payload = asdict(snapshot)
        payload["path"] = str(path)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return snapshot


def _require_success(command_name: str, completed: object) -> str:
    returncode = getattr(completed, "returncode")
    stdout = getattr(completed, "stdout")
    stderr = getattr(completed, "stderr")
    if returncode != 0:
        raise RuntimeError(f"{command_name} failed: {stderr or stdout}")
    return str(stdout)
