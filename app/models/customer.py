"""Typed customer and vehicle data for the BDC domain."""

from dataclasses import dataclass
from datetime import date
from enum import Enum
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.service_history import ServiceHistoryEntry


DEALERSHIPS = frozenset({"Chevrolet", "Kia"})
BDC_AGENTS = frozenset({"Lucas", "Tracy", "Emily", "Ralphy", "Cassandra"})
VIN_PATTERN = re.compile(r"^[A-Za-z0-9]{8}$")


class ServicePattern(str, Enum):
    """Supported intervals for recurring customer service."""

    EVERY_3_MONTHS = "every 3 months"
    EVERY_5_MONTHS = "every 5 months"
    EVERY_6_MONTHS = "every 6 months"
    ONCE_A_YEAR = "once a year"


@dataclass(frozen=True)
class Vehicle:
    """A customer's vehicle and its current odometer reading."""

    make: str
    model: str
    year: int
    vin: str
    current_mileage: int

    def __post_init__(self) -> None:
        if not self.make.strip() or not self.model.strip():
            raise ValueError("Vehicle make and model are required")
        if not 1886 <= self.year <= date.today().year + 1:
            raise ValueError("Vehicle year is outside the supported range")
        if not VIN_PATTERN.fullmatch(self.vin):
            raise ValueError("VIN must be exactly 8 alphanumeric characters")
        if self.current_mileage < 0:
            raise ValueError("Current mileage cannot be negative")


@dataclass(frozen=True)
class Customer:
    """A customer with service history and assigned BDC ownership."""

    customer_name: str
    email: str
    phone: str
    dealership: str
    vehicle: Vehicle
    last_service_date: date
    service_pattern: ServicePattern
    bdc_agent: str
    service_history: tuple["ServiceHistoryEntry", ...] = ()

    def __post_init__(self) -> None:
        if not self.customer_name.strip():
            raise ValueError("Customer name is required")
        if "@" not in self.email or not self.email.strip():
            raise ValueError("A valid customer email is required")
        if not self.phone.strip():
            raise ValueError("Customer phone is required")
        if self.dealership not in DEALERSHIPS:
            raise ValueError("Dealership must be Chevrolet or Kia")
        if self.bdc_agent not in BDC_AGENTS:
            raise ValueError("BDC agent is not recognized")
