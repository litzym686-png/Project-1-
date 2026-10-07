from datetime import date

import pytest

from app.models.customer import ServicePattern
from app.services.service_schedule import (
    add_months,
    is_service_due,
    next_service_date,
)


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        (ServicePattern.EVERY_3_MONTHS, date(2025, 4, 15)),
        (ServicePattern.EVERY_5_MONTHS, date(2025, 6, 15)),
        (ServicePattern.EVERY_6_MONTHS, date(2025, 7, 15)),
        (ServicePattern.ONCE_A_YEAR, date(2026, 1, 15)),
    ],
)
def test_next_service_date_for_each_pattern(pattern, expected):
    assert next_service_date(date(2025, 1, 15), pattern) == expected


def test_add_months_clamps_end_of_month():
    assert add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)


def test_service_is_due_on_expected_date_but_not_before():
    expected = date(2025, 7, 31)

    assert not is_service_due(expected, date(2025, 7, 30))
    assert is_service_due(expected, expected)
