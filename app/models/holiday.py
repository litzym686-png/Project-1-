"""Immutable dealership-specific holiday closure calendars."""

from dataclasses import dataclass
from datetime import date, timedelta

from app.models.customer import DEALERSHIPS


@dataclass(frozen=True)
class HolidayClosure:
    """A named date when a dealership is closed."""

    closure_date: date
    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Holiday closure name is required")


@dataclass(frozen=True)
class HolidayCalendar:
    """A dealership's configurable closure dates.

    A reminder due on a closure date is deferred to the next open calendar day.
    """

    dealership: str
    closures: tuple[HolidayClosure, ...] = ()

    def __post_init__(self) -> None:
        if self.dealership not in DEALERSHIPS:
            raise ValueError("Holiday calendar dealership is not recognized")
        closure_dates = [closure.closure_date for closure in self.closures]
        if len(closure_dates) != len(set(closure_dates)):
            raise ValueError("Holiday calendar cannot contain duplicate dates")

    def closure_for(self, calendar_date: date) -> HolidayClosure | None:
        """Return the closure affecting a date, if any."""
        return next(
            (
                closure
                for closure in self.closures
                if closure.closure_date == calendar_date
            ),
            None,
        )

    def next_open_date(self, calendar_date: date) -> date:
        """Return the first open date on or after the supplied date."""
        next_date = calendar_date
        while self.closure_for(next_date) is not None:
            next_date += timedelta(days=1)
        return next_date
