"""Twenty fictional customers balanced across the two dealerships."""

from datetime import date

from app.models.customer import Customer, ServicePattern, Vehicle


def _customer(
    number: int,
    dealership: str,
    agent: str,
    pattern: ServicePattern,
) -> Customer:
    """Build one deterministic fictional customer record."""
    make = dealership
    model = "Equinox" if dealership == "Chevrolet" else "Sportage"
    return Customer(
        customer_name=f"Fictional Customer {number:02d}",
        email=f"customer{number:02d}@example.test",
        phone=f"555-010-{number:02d}",
        dealership=dealership,
        vehicle=Vehicle(
            make=make,
            model=model,
            year=2020 + number % 5,
            vin=f"FIC{number:05d}",
            current_mileage=12000 + number * 1375,
        ),
        last_service_date=date(2025, (number - 1) % 12 + 1, 15),
        service_pattern=pattern,
        bdc_agent=agent,
    )


FICTIONAL_CUSTOMERS = tuple(
    _customer(
        number,
        "Chevrolet" if number <= 10 else "Kia",
        ("Lucas", "Tracy", "Emily", "Ralphy", "Cassandra")[(number - 1) % 5],
        (
            ServicePattern.EVERY_3_MONTHS,
            ServicePattern.EVERY_5_MONTHS,
            ServicePattern.EVERY_6_MONTHS,
            ServicePattern.ONCE_A_YEAR,
        )[(number - 1) % 4],
    )
    for number in range(1, 21)
)
