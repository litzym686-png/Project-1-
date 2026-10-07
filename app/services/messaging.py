"""Pure generation of fictional service reminder drafts."""

from datetime import date

from app.models.customer import Customer
from app.models.message import MessageChannel, MessageDraft
from app.services.customer_service import expected_service_date, is_customer_due


def generate_service_reminder(
    customer: Customer,
    current_date: date,
    channel: MessageChannel = MessageChannel.EMAIL,
) -> MessageDraft | None:
    """Draft a reminder only when the customer is due for service."""
    if not is_customer_due(customer, current_date):
        return None
    expected_date = expected_service_date(customer)
    body = (
        f"Hello {customer.customer_name}, your {customer.vehicle.year} "
        f"{customer.vehicle.make} {customer.vehicle.model} is due for service. "
        f"Please contact {customer.dealership} to schedule an appointment."
    )
    return MessageDraft(
        customer_name=customer.customer_name,
        contact=customer.email if channel is MessageChannel.EMAIL else customer.phone,
        channel=channel,
        body=f"{body} The expected service date was {expected_date.isoformat()}.",
    )
