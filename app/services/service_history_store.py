"""Durable storage for completed vehicle service visits."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

from app.models.service_history import ServiceHistoryEntry


def default_service_history_path() -> Path:
    """Return a user-local store path outside the source tree."""
    return Path.home() / ".service-center" / "service_history.json"


class ServiceHistoryStore:
    """Persist completed service entries as a small atomic JSON document."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_service_history_path()

    def load(self) -> dict[str, tuple[ServiceHistoryEntry, ...]]:
        """Load records keyed by vehicle VIN, returning an empty store if absent."""
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Service history root must be an object")
            return {
                str(vin): tuple(_entry_from_dict(item) for item in entries)
                for vin, entries in payload.items()
            }
        except (OSError, TypeError, ValueError, KeyError) as error:
            raise RuntimeError("Service history store could not be read") from error

    def save(
        self,
        vehicle_vin: str,
        entries: tuple[ServiceHistoryEntry, ...],
    ) -> None:
        """Atomically save one vehicle's completed history."""
        records = self.load()
        records[vehicle_vin] = entries
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            vin: [_entry_to_dict(entry) for entry in vehicle_entries]
            for vin, vehicle_entries in records.items()
        }
        fd, temporary_name = tempfile.mkstemp(
            prefix="service-history-", suffix=".json", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temporary:
                json.dump(payload, temporary, indent=2, sort_keys=True)
                temporary.write("\n")
            Path(temporary_name).replace(self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


def _entry_to_dict(entry: ServiceHistoryEntry) -> dict[str, object]:
    """Convert one immutable entry to JSON-compatible data."""
    return {
        "service_date": entry.service_date.isoformat(),
        "mileage": entry.mileage,
        "service_type": entry.service_type,
        "notes": entry.notes,
        "description": entry.description,
        "technician": entry.technician,
    }


def _entry_from_dict(value: dict[str, object]) -> ServiceHistoryEntry:
    """Restore and validate one persisted service entry."""
    return ServiceHistoryEntry(
        service_date=date.fromisoformat(str(value["service_date"])),
        mileage=int(value["mileage"]),
        service_type=str(value["service_type"]),
        notes=_optional_text(value.get("notes")),
        description=_optional_text(value.get("description")),
        technician=_optional_text(value.get("technician")),
    )


def _optional_text(value: object) -> str | None:
    """Normalize optional persisted text without inventing values."""
    return None if value is None else str(value)
