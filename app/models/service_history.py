"""Immutable service history records."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ServiceHistoryEntry:
    """A completed service event for a customer's vehicle."""

    service_date: date
    mileage: int
    service_type: str
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.mileage < 0:
            raise ValueError("Service mileage cannot be negative")
        if not self.service_type.strip():
            raise ValueError("Service type is required")
