"""In-memory appointment records for the local dashboard calendar."""

from dataclasses import dataclass
from datetime import date, time


@dataclass(frozen=True)
class Appointment:
    """A scheduled appointment tied to an existing customer and vehicle."""

    customer_name: str
    vin: str
    dealership: str
    assigned_agent: str
    scheduled_date: date
    scheduled_time: time
    is_demo: bool = False

