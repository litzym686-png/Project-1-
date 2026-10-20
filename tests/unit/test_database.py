from datetime import date, time

import pytest

from app.data.seed_customers import FICTIONAL_CUSTOMERS
from app.models.service_history import ServiceHistoryEntry
from app.services.database import Database, DatabaseError


def _db(tmp_path):
    database = Database(tmp_path / "dashboard.db")
    database.seed_customers(FICTIONAL_CUSTOMERS)
    return database


def test_seed_creates_stable_unique_customer_ids_without_duplicates(tmp_path):
    database = _db(tmp_path)
    first = database.customers()
    database.seed_customers(FICTIONAL_CUSTOMERS)
    again = Database(tmp_path / "dashboard.db")
    again.seed_customers(FICTIONAL_CUSTOMERS)

    assert len(first) == 20 and len({row["id"] for row in first}) == 20
    assert again.customers() == first
    assert first[0]["id"] == "CUST-0001"
    maya = FICTIONAL_CUSTOMERS[0]
    assert database.customer_id(maya.vehicle.vin) == "CUST-0001"
    assert first[0]["dealership"] == maya.dealership


def test_unknown_vin_is_rejected(tmp_path):
    with pytest.raises(DatabaseError):
        _db(tmp_path).customer_id("NOSUCHVN")


def test_records_persist_and_stay_with_their_customer(tmp_path):
    database = _db(tmp_path)
    a, b = FICTIONAL_CUSTOMERS[0], FICTIONAL_CUSTOMERS[-1]
    entry = ServiceHistoryEntry(date(2027, 1, 5), 1000, "Oil change", "n", "work", "Lucas", "Noise")
    database.save_visit(a.vehicle.vin, a.dealership, entry)
    database.save_appointment(a.vehicle.vin, a.dealership, a.bdc_agent, date(2027, 2, 1), time(9, 30))
    database.save_message(a.vehicle.vin, a.dealership, "outgoing", "Lucas", "hi", "Simulated send")
    database.save_message(a.vehicle.vin, a.dealership, "incoming", a.customer_name, "ok", "Demo reply")

    reopened = Database(tmp_path / "dashboard.db")
    assert reopened.visits_by_vin() == {a.vehicle.vin: (entry,)}
    assert b.vehicle.vin not in reopened.visits_by_vin()
    appointments = reopened.appointment_rows()
    assert [(r["name"], r["vin"], r["dealership"]) for r in appointments] == [
        (a.customer_name, a.vehicle.vin, a.dealership)
    ]
    assert [m["direction"] for m in reopened.message_rows(a.vehicle.vin)] == ["outgoing", "incoming"]
    assert reopened.message_rows(b.vehicle.vin) == ()


def test_existing_database_is_backed_up_on_open(tmp_path):
    _db(tmp_path)
    Database(tmp_path / "dashboard.db")

    assert list((tmp_path / "backups").glob("dashboard-2*.db"))


def test_corrupt_database_is_preserved_and_reported_not_replaced(tmp_path):
    path = tmp_path / "dashboard.db"
    path.write_bytes(b"this is not a sqlite database" * 10)
    original = path.read_bytes()

    with pytest.raises(DatabaseError, match="NOT changed"):
        Database(path)

    assert path.read_bytes() == original
    assert list((tmp_path / "backups").glob("dashboard-corrupt-*.db"))
