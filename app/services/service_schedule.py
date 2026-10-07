"""Pure service-pattern and calendar calculations."""

from calendar import monthrange
from datetime import date

from app.models.customer import ServicePattern
from app.models.service_history import ServiceHistoryEntry


_MONTH_INTERVALS = {
    ServicePattern.EVERY_3_MONTHS: 3,
    ServicePattern.EVERY_5_MONTHS: 5,
    ServicePattern.EVERY_6_MONTHS: 6,
    ServicePattern.ONCE_A_YEAR: 12,
}


def add_months(start_date: date, months: int) -> date:
    """Add calendar months while clamping to the destination month."""
    target_month = start_date.month - 1 + months
    year = start_date.year + target_month // 12
    month = target_month % 12 + 1
    day = min(start_date.day, monthrange(year, month)[1])
    return date(year, month, day)


def next_service_date(last_service_date: date, pattern: ServicePattern) -> date:
    """Calculate the next expected service date for a supported pattern."""
    try:
        months = _MONTH_INTERVALS[pattern]
    except KeyError as error:
        raise ValueError("Unsupported service pattern") from error
    return add_months(last_service_date, months)


def is_service_due(next_expected_date: date, current_date: date) -> bool:
    """Return whether service is due on or before the supplied current date."""
    return current_date >= next_expected_date


def latest_service_date(
    service_history: tuple[ServiceHistoryEntry, ...],
    fallback_date: date,
) -> date:
    """Return the latest recorded service date or the legacy fallback date."""
    if not service_history:
        return fallback_date
    return max(entry.service_date for entry in service_history)
