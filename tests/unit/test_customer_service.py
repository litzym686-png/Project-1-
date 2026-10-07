from datetime import date

from app.data.seed_customers import FICTIONAL_CUSTOMERS
from app.models.customer import Customer, ServicePattern, Vehicle
from app.services.customer_service import expected_service_date, is_customer_due


def _customer(pattern=ServicePattern.EVERY_3_MONTHS):
    return Customer(
        customer_name="Test Customer",
        email="test@example.test",
        phone="555-010-99",
        dealership="Chevrolet",
        vehicle=Vehicle("Chevrolet", "Equinox", 2024, "TEST1234", 1000),
        last_service_date=date(2025, 1, 15),
        service_pattern=pattern,
        bdc_agent="Lucas",
    )


def test_customer_service_delegates_to_pattern_calculation():
    customer = _customer(ServicePattern.ONCE_A_YEAR)

    assert expected_service_date(customer) == date(2026, 1, 15)


def test_customer_due_status_uses_supplied_current_date():
    customer = _customer()

    assert not is_customer_due(customer, date(2025, 4, 14))
    assert is_customer_due(customer, date(2025, 4, 15))


def test_seed_data_has_twenty_customers_balanced_by_dealership():
    assert len(FICTIONAL_CUSTOMERS) == 20
    assert sum(customer.dealership == "Chevrolet" for customer in FICTIONAL_CUSTOMERS) == 10
    assert sum(customer.dealership == "Kia" for customer in FICTIONAL_CUSTOMERS) == 10
