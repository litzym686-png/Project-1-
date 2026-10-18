"""Pure generation of fictional service reminder drafts."""

from datetime import date

from app.models.customer import Customer, CustomerLanguage
from app.models.holiday import HolidayCalendar, HolidayClosure
from app.models.message import MessageChannel, MessageDraft
from app.services.customer_service import expected_service_date, is_customer_due

_ENGLISH_REMINDER_TEMPLATE = (
    "Hello {name}, your {year} {make} {model} is due for service. "
    "Please contact {dealership} to schedule an appointment. "
    "The expected service date was {expected_date}."
)
_SPANISH_REMINDER_TEMPLATE = (
    "Hola {name}, su {year} {make} {model} necesita servicio. "
    "Comuníquese con {dealership} para programar una cita. "
    "La fecha de servicio prevista era {expected_date}."
)


def generate_service_reminder(
    customer: Customer,
    current_date: date,
    channel: MessageChannel = MessageChannel.EMAIL,
    holiday_calendar: HolidayCalendar | None = None,
) -> MessageDraft | None:
    """Draft a reminder, deferring a closure-date due reminder to an open date."""
    _validate_calendar(customer, holiday_calendar)
    if not is_customer_due(customer, current_date):
        return None
    expected_date = expected_service_date(customer)
    closure = (
        holiday_calendar.closure_for(expected_date)
        if holiday_calendar is not None
        else None
    )
    deferred_date = (
        holiday_calendar.next_open_date(expected_date)
        if closure is not None and holiday_calendar is not None
        else None
    )
    return MessageDraft(
        customer_name=customer.customer_name,
        contact=customer.email if channel is MessageChannel.EMAIL else customer.phone,
        channel=channel,
        body=_reminder_body(customer, expected_date, closure, deferred_date),
        language_preference=customer.language_preference,
    )


def _reminder_body(
    customer: Customer,
    expected_date: date,
    closure: HolidayClosure | None,
    deferred_date: date | None,
) -> str:
    """Build the reminder copy in the customer's preferred language."""
    if closure is not None and deferred_date is not None:
        if customer.language_preference is CustomerLanguage.SPANISH:
            return (
                f"Hola {customer.customer_name}, su fecha de servicio prevista era "
                f"{expected_date.isoformat()}. {customer.dealership} estará cerrado "
                f"por {closure.name}, así que este recordatorio se pospone al "
                f"{deferred_date.isoformat()}."
            )
        return (
            f"Hello {customer.customer_name}, your expected service date was "
            f"{expected_date.isoformat()}. {customer.dealership} is closed for "
            f"{closure.name}, so this reminder is deferred to "
            f"{deferred_date.isoformat()}."
        )
    template = (
        _SPANISH_REMINDER_TEMPLATE
        if customer.language_preference is CustomerLanguage.SPANISH
        else _ENGLISH_REMINDER_TEMPLATE
    )
    return template.format(
        name=customer.customer_name,
        year=customer.vehicle.year,
        make=customer.vehicle.make,
        model=customer.vehicle.model,
        dealership=customer.dealership,
        expected_date=expected_date.isoformat(),
    )


def _validate_calendar(
    customer: Customer,
    holiday_calendar: HolidayCalendar | None,
) -> None:
    """Prevent one dealership's closure rules from affecting another."""
    if (
        holiday_calendar is not None
        and holiday_calendar.dealership != customer.dealership
    ):
        raise ValueError("Holiday calendar dealership does not match customer")
