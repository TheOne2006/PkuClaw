from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Job:
    kind: str
    status: str = "queued"
    created_at: datetime = field(default_factory=datetime.now)
    payload: dict = field(default_factory=dict)
