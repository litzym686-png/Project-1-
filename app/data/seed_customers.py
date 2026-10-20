"""Twenty fictional customers balanced across the two dealerships."""

from datetime import date

from app.models.customer import Customer, CustomerLanguage, ServicePattern, Vehicle

_CHEVROLET_CONTACTS = (
    ("Maya Rodriguez", "maya.rodriguez@fake.email.com", "(555) 010-1001"),
    ("Ethan Parker", "ethan.parker@fake.email.com", "(555) 010-1002"),
    ("Sofia Bennett", "sofia.bennett@fake.email.com", "(555) 010-1003"),
    ("Ariana Collins", "ariana.collins@fake.email.com", "(555) 010-1005"),
    ("Noah Anderson", "noah.anderson@fake.email.com", "(555) 010-1006"),
    ("Valeria Thompson", "valeria.thompson@fake.email.com", "(555) 010-1007"),
    ("Daniel Foster", "daniel.foster@fake.email.com", "(555) 010-1008"),
    ("Saturo Gojo", "gojo.saturo@fake.email.com", "(555) 010-1015"),
    ("Muzan Kibutsuji", "muzankibutsuji@fake.email.com", "(555) 010-1017"),
    ("Yoichi Nagumo", "yoichinagumo@fake.email.com", "(555) 010-1019"),
)
_KIA_CONTACTS = (
    ("Camila Brooks", "camila.brooks@fake.email.com", "(555) 010-1009"),
    ("Inosuske Hashibira", "inosuskehashibira@fake.email.com", "(555) 010-1016"),
    ("Jordan Ramirez", "jordan.ramirez@fake.email.com", "(555) 010-1010"),
    ("Elena Morgan", "elena.morgan@fake.email.com", "(555) 010-1011"),
    ("Marcus Sullivan", "marcus.sullivan@fake.email.com", "(555) 010-1012"),
    ("Natalie Hayes", "natalie.hayes@fake.email.com", "(555) 010-1013"),
    ("Tristan Mitchell", "lucas.mitchell@fake.email.com", "(555) 010-1004"),
    ("Toji Fushiguro", "toji.fushiguro@fake.email.com", "(555) 010-1014"),
    ("Tengen Uzui", "tengenuzui@fake.email.com", "(555) 010-1018"),
    ("Taro Sakamato", "tarosakamato@fake.email.com", "(555) 010-1020"),
)


def _customer(
    number: int,
    dealership: str,
    agent: str,
    pattern: ServicePattern,
) -> Customer:
    """Build one deterministic fictional customer record."""
    contacts = _CHEVROLET_CONTACTS if dealership == "Chevrolet" else _KIA_CONTACTS
    customer_name, email, phone = contacts[(number - 1) % len(contacts)]
    make = dealership
    models = (
        ("Equinox", "Traverse", "Tahoe")
        if dealership == "Chevrolet"
        else ("Sportage", "Sorento", "Telluride")
    )
    model = models[(number - 1) % len(models)]
    return Customer(
    customer_name=customer_name,
    email=email,
    phone=phone,
    dealership=dealership,
    vehicle=Vehicle(
        make=make,
        model=model,
        year=2020 + number % 5,
        vin=f"FIC{number:05d}",
        current_mileage=(20000, 30000, 45000, 60000)[(number - 1) % 4],
    ),
    last_service_date=date(2025, (number - 1) % 12 + 1, 15),
    service_pattern=pattern,
    bdc_agent=agent,
    language_preference=(
        CustomerLanguage.SPANISH
        if number % 5 == 0
        else CustomerLanguage.ENGLISH
    ),
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