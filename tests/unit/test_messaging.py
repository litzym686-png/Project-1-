from datetime import date

from app.models.customer import Customer, ServicePattern, Vehicle
from app.models.message import MessageChannel
from app.models.service_history import ServiceHistoryEntry
from app.services.messaging import generate_service_reminder


def _customer():
    return Customer(
        customer_name="Test Customer",
        email="test@example.test",
        phone="555-010-99",
        dealership="Kia",
        vehicle=Vehicle("Kia", "Sportage", 2024, "TEST1234", 1000),
        last_service_date=date(2025, 1, 15),
        service_pattern=ServicePattern.EVERY_3_MONTHS,
        bdc_agent="Lucas",
        service_history=(
            ServiceHistoryEntry(date(2025, 2, 28), 1200, "Oil change"),
        ),
    )


def test_due_customer_gets_email_draft_using_latest_history():
    draft = generate_service_reminder(_customer(), date(2025, 6, 1))

    assert draft is not None
    assert draft.channel is MessageChannel.EMAIL
    assert draft.contact == "test@example.test"
    assert "due for service" in draft.body
    assert "2025-05-28" in draft.body


def test_not_due_customer_does_not_get_a_draft():
    assert generate_service_reminder(_customer(), date(2025, 5, 27)) is None
