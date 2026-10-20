from datetime import date

import pytest

from app.models.customer import Customer, ServicePattern, Vehicle
from app.models.customer import CustomerLanguage
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


def _customer_with_language(language):
    return Customer(
        customer_name="Test Customer",
        email="test@example.test",
        phone="555-010-99",
        dealership="Kia",
        vehicle=Vehicle("Kia", "Sportage", 2024, "TEST1234", 1000),
        last_service_date=date(2025, 1, 15),
        service_pattern=ServicePattern.EVERY_3_MONTHS,
        bdc_agent="Lucas",
        language_preference=language,
    )


def test_due_customer_gets_email_draft_using_latest_history():
    draft = generate_service_reminder(_customer(), date(2025, 6, 1))

    assert draft is not None
    assert draft.channel is MessageChannel.EMAIL
    assert draft.contact == "test@example.test"
    assert "due for service" in draft.body
    assert "2025-05-28" in draft.body


def test_missing_language_preference_defaults_to_english():
    customer = _customer()

    assert customer.language_preference is CustomerLanguage.ENGLISH
    draft = generate_service_reminder(customer, date(2025, 6, 1))

    assert draft is not None
    assert draft.body == (
        "Hello Test, your 2024 Kia Sportage is due for service. "
        "Please contact Kia to schedule an appointment. "
        "The expected service date was 2025-05-28."
    )


def test_spanish_language_preference_generates_spanish_draft():
    draft = generate_service_reminder(
        _customer_with_language(CustomerLanguage.SPANISH),
        date(2025, 6, 1),
    )

    assert draft is not None
    assert draft.body == (
        "Hola Test, su 2024 Kia Sportage necesita servicio. "
        "Comuníquese con Kia para programar una cita. "
        "La fecha de servicio prevista era 2025-04-15."
    )


def test_invalid_language_preference_is_rejected():
    with pytest.raises(ValueError, match="language preference is not supported"):
        _customer_with_language("fr")


def test_not_due_customer_does_not_get_a_draft():
    assert generate_service_reminder(_customer(), date(2025, 5, 27)) is None


def test_automated_reminders_greet_first_name_only_in_both_languages():
    from dataclasses import replace

    from app.data.seed_customers import FICTIONAL_CUSTOMERS

    for customer in FICTIONAL_CUSTOMERS[:6]:
        for language, greeting in ((CustomerLanguage.ENGLISH, "Hello"), (CustomerLanguage.SPANISH, "Hola")):
            draft = generate_service_reminder(
                replace(customer, language_preference=language), date(2030, 1, 1)
            )
            first, *rest = customer.customer_name.split()
            assert draft.body.startswith(f"{greeting} {first},")
            assert all(part not in draft.body for part in rest)
            assert draft.customer_name == customer.customer_name
