from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Event:
    kind: str
    title: str
    source: str
    occurred_at: datetime
    payload: dict
