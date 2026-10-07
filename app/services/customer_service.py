"""Customer-facing service status behavior."""

from datetime import date

from app.models.customer import Customer
from app.services.service_schedule import (
    is_service_due,
    latest_service_date,
    next_service_date,
)


def expected_service_date(customer: Customer) -> date:
    """Return the customer's next expected service date."""
    anchor_date = latest_service_date(
        customer.service_history,
        customer.last_service_date,
    )
    return next_service_date(anchor_date, customer.service_pattern)


def is_customer_due(customer: Customer, current_date: date) -> bool:
    """Return whether a customer is due for service on a given date."""
    return is_service_due(expected_service_date(customer), current_date)
