from datetime import date

from app.models.customer import Customer, ServicePattern, Vehicle
from app.models.service_history import ServiceHistoryEntry
from app.services.customer_service import expected_service_date


def _customer(history):
    return Customer(
        customer_name="Test Customer",
        email="test@example.test",
        phone="555-010-99",
        dealership="Chevrolet",
        vehicle=Vehicle("Chevrolet", "Equinox", 2024, "TEST1234", 1000),
        last_service_date=date(2025, 1, 15),
        service_pattern=ServicePattern.EVERY_6_MONTHS,
        bdc_agent="Lucas",
        service_history=history,
    )


def test_latest_history_entry_controls_next_expected_service_date():
    customer = _customer(
        (
            ServiceHistoryEntry(date(2025, 1, 31), 1000, "Inspection"),
            ServiceHistoryEntry(date(2025, 3, 31), 1500, "Tire rotation"),
        ),
    )

    assert expected_service_date(customer) == date(2025, 9, 30)
