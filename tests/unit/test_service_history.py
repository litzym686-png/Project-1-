from datetime import date

from app.models.customer import Customer, ServicePattern, Vehicle
from app.models.service_history import ServiceHistoryEntry
from app.services.customer_service import expected_service_date
from app.services.dashboard import DashboardState
from app.services.service_history_store import ServiceHistoryStore


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


def test_dashboard_service_visit_recalculates_expected_date():
    dashboard = DashboardState(
        customers=(_customer(()),),
        current_date=date(2025, 7, 1),
    )

    updated = dashboard.record_service_visit(
        "Test Customer",
        date(2025, 6, 30),
        2500,
        "Oil change",
        "Completed in shop",
    )

    assert updated.service_history[-1].mileage == 2500
    assert updated.service_history[-1].notes == "Completed in shop"
    assert dashboard.rows()[0].expected_date == date(2025, 12, 30)
    assert dashboard.rows()[0].draft is None


def test_service_history_persists_across_dashboard_state_restart(tmp_path):
    store = ServiceHistoryStore(tmp_path / "service-history.json")
    dashboard = DashboardState(customers=(_customer(()),), history_store=store)

    dashboard.record_service_visit(
        "Test Customer",
        date(2025, 6, 30),
        2500,
        "Oil and filter change",
        "Customer requested synthetic oil",
        "Replaced oil and filter; inspected fluids",
        "Lucas",
    )

    restarted = DashboardState(customers=(_customer(()),), history_store=store)
    entry = restarted.customers[0].service_history[0]

    assert entry.service_type == "Oil and filter change"
    assert entry.description == "Replaced oil and filter; inspected fluids"
    assert entry.technician == "Lucas"
    assert entry.notes == "Customer requested synthetic oil"
    assert restarted.customers[0].last_service_date == date(2025, 6, 30)
    assert restarted.customers[0].vehicle.current_mileage == 2500


def test_service_history_is_newest_first_and_due_date_uses_latest_visit(tmp_path):
    store = ServiceHistoryStore(tmp_path / "service-history.json")
    dashboard = DashboardState(customers=(_customer(()),), history_store=store)

    dashboard.record_service_visit("Test Customer", date(2025, 3, 1), 1800, "Inspection")
    dashboard.record_service_visit("Test Customer", date(2025, 7, 1), 2500, "Tire rotation")

    visits = dashboard.service_history()

    assert [entry.service_date for _, entry in visits] == [
        date(2025, 7, 1),
        date(2025, 3, 1),
    ]
    assert dashboard.rows()[0].expected_date == date(2026, 1, 1)
