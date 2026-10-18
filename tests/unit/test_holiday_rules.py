from dataclasses import replace
from datetime import date

import pytest

from app.models.customer import CustomerLanguage
from app.models.holiday import HolidayCalendar, HolidayClosure
from app.models.message import MessageStatus
from app.models.outbox import OutboxStatus
from app.services.message_outbox import mark_simulated_sent, queue_approved_message
from app.services.message_review import approve_draft
from app.services.message_routing import route_message_drafts
from app.services.messaging import generate_service_reminder

from tests.unit.test_messaging import _customer, _customer_with_language


def _kia_calendar(*closures: HolidayClosure) -> HolidayCalendar:
    return HolidayCalendar("Kia", closures)


def test_due_closed_date_is_deferred_to_next_open_calendar_day():
    customer = _customer()
    calendar = _kia_calendar(
        HolidayClosure(date(2025, 5, 28), "Kia inventory closure"),
        HolidayClosure(date(2025, 5, 29), "Kia inventory closure"),
    )

    draft = generate_service_reminder(customer, date(2025, 6, 1), holiday_calendar=calendar)

    assert draft is not None
    assert draft.body == (
        "Hello Test Customer, your expected service date was 2025-05-28. "
        "Kia is closed for Kia inventory closure, so this reminder is deferred "
        "to 2025-05-30."
    )


def test_due_normal_business_day_keeps_existing_reminder_copy():
    customer = _customer()
    calendar = _kia_calendar(HolidayClosure(date(2025, 6, 1), "Kia closure"))

    draft = generate_service_reminder(customer, date(2025, 6, 1), holiday_calendar=calendar)

    assert draft is not None
    assert "due for service" in draft.body
    assert "deferred" not in draft.body


def test_dealership_holiday_calendar_cannot_affect_another_dealership():
    customer = replace(_customer(), dealership="Chevrolet")
    kia_calendar = _kia_calendar(HolidayClosure(date(2025, 5, 28), "Kia closure"))

    with pytest.raises(ValueError, match="does not match customer"):
        generate_service_reminder(
            customer,
            date(2025, 6, 1),
            holiday_calendar=kia_calendar,
        )


def test_deferred_spanish_draft_survives_review_routing_and_outbox():
    customer = _customer_with_language(CustomerLanguage.SPANISH)
    calendar = _kia_calendar(HolidayClosure(date(2025, 4, 15), "Cierre de Kia"))
    draft = generate_service_reminder(
        customer,
        date(2025, 6, 1),
        holiday_calendar=calendar,
    )

    routed = route_message_drafts((customer,), (draft,))[0]
    approved = approve_draft(routed)
    queued = queue_approved_message(approved)
    sent = mark_simulated_sent(queued)

    assert sent.draft.body == (
        "Hola Test Customer, su fecha de servicio prevista era 2025-04-15. "
        "Kia estará cerrado por Cierre de Kia, así que este recordatorio se "
        "pospone al 2025-04-16."
    )
    assert sent.draft.language_preference is CustomerLanguage.SPANISH
    assert sent.draft.status == MessageStatus.APPROVED.value
    assert sent.status is OutboxStatus.SIMULATED_SENT
    assert sent.dealership == customer.dealership
    assert sent.assigned_agent == customer.bdc_agent
