"""Append-only ledger of run events (JSON lines).

Every event is a UTC ISO-8601, timestamped JSON record on disk before it is
formatted for a human. Nothing is written that was not produced by real code.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> str:
    """UTC timestamp with millisecond precision and an explicit ``Z``."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_run_id() -> str:
    """UTC sortable run id with a short random suffix to avoid collisions."""
    return "run-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)


class RunEvent(BaseModel):
    """One pipeline event, serialised as a single JSON line."""

    ts: str
    event: str
    data: dict[str, Any] = Field(default_factory=dict)


class RunLedger:
    """Writes events to ``<directory>/events.jsonl`` as they happen."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "events.jsonl"

    def append(self, event: str, **data: Any) -> None:
        """Append one event; flush and close before returning."""
        record = RunEvent(ts=utc_now(), event=event, data=data)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")

    def read_all(self) -> list[RunEvent]:
        """Read every valid line; invalid lines are an error, not skipped."""
        if not self.path.exists():
            return []
        events: list[RunEvent] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            events.append(RunEvent.model_validate_json(line))
        return events

    def read_last(self) -> RunEvent | None:
        """Return the most recent event, if any."""
        events = self.read_all()
        return events[-1] if events else None
