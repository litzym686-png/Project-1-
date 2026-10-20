import sqlite3
from datetime import date, time

import pytest

from app.services.dashboard import DashboardState
from app.services.database import Database


def _state(path):
    return DashboardState(database=Database(path))


def _customer(state, index=0):
    return state.customers[index]


def test_every_customer_starts_with_a_varied_mileage(tmp_path):
    state = _state(tmp_path / "d.db")
    mileages = {c.vehicle.current_mileage for c in state.customers}
    assert mileages <= {20000, 30000, 45000, 60000}
    assert len(mileages) > 1


def test_appointment_persists_with_details_and_defaults_to_current_mileage(tmp_path):
    path = tmp_path / "d.db"
    state = _state(path)
    maya = _customer(state)
    state.schedule_appointment(maya.customer_name, date(2027, 2, 1), time(10, 30),
                               "Express Shop", " Oil change ")
    reopened = _state(path)
    saved = [a for a in reopened.appointments if a.scheduled_date == date(2027, 2, 1)]
    assert len(saved) == 1
    appt = saved[0]
    assert (appt.vin, appt.dealership, appt.assigned_agent) == (
        maya.vehicle.vin, maya.dealership, maya.bdc_agent)
    assert (appt.status, appt.service_type, appt.reason) == ("scheduled", "Express Shop", "Oil change")
    assert appt.mileage == maya.vehicle.current_mileage
    assert appt.scheduled_time == time(10, 30)


def test_rescheduling_same_slot_updates_instead_of_duplicating(tmp_path):
    state = _state(tmp_path / "d.db")
    name = _customer(state).customer_name
    state.schedule_appointment(name, date(2027, 2, 1), time(9, 0), "Main Shop", "a")
    state.schedule_appointment(name, date(2027, 2, 1), time(9, 0), "Express Shop", "b")
    rows = state.database.appointment_rows()
    matching = [r for r in rows if r["scheduled_date"] == "2027-02-01"]
    assert len(matching) == 1 and matching[0]["reason"] == "b"


def test_recording_service_updates_current_mileage_and_next_appointment(tmp_path):
    path = tmp_path / "d.db"
    state = _state(path)
    maya = _customer(state)
    new_mileage = maya.vehicle.current_mileage + 1200
    state.record_service_visit(maya.customer_name, date(2027, 1, 10), new_mileage,
                               "Main Shop", "n", None, "Tracy", "Brakes")
    reopened = _state(path)
    assert reopened.customers[0].vehicle.current_mileage == new_mileage
    appt = reopened.schedule_appointment(maya.customer_name, date(2027, 3, 1), time(9, 0))
    assert appt.mileage == new_mileage


def test_older_visit_does_not_lower_current_mileage_and_keeps_own_mileage(tmp_path):
    path = tmp_path / "d.db"
    state = _state(path)
    maya = _customer(state)
    high = maya.vehicle.current_mileage + 5000
    state.record_service_visit(maya.customer_name, date(2027, 1, 20), high, "Main Shop")
    state.record_service_visit(maya.customer_name, date(2026, 6, 1), high - 3000, "Express Shop")
    reopened = _state(path)
    customer = reopened.customers[0]
    assert customer.vehicle.current_mileage == high
    assert sorted(e.mileage for e in customer.service_history) == [high - 3000, high]
    with sqlite3.connect(path) as db:
        stored = db.execute("SELECT current_mileage FROM customers WHERE vin = ?",
                            (maya.vehicle.vin,)).fetchone()[0]
    assert stored == high


@pytest.mark.parametrize("bad", [-1, "abc", "12.5", "", True, 3.5])
def test_invalid_mileage_is_rejected(tmp_path, bad):
    state = _state(tmp_path / "d.db")
    name = _customer(state).customer_name
    with pytest.raises(ValueError):
        state.record_service_visit(name, date(2027, 1, 10), bad, "Main Shop")
    with pytest.raises(ValueError):
        state.schedule_appointment(name, date(2027, 2, 1), time(9, 0), mileage=bad)
    assert _customer(state).service_history == ()


def test_existing_sofia_style_mileage_is_preserved_on_initialization(tmp_path):
    path = tmp_path / "d.db"
    state = _state(path)
    sofia = _customer(state, 2)
    state.record_service_visit(sofia.customer_name, date(2026, 10, 20), 60000, "Main Shop")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE customers SET current_mileage = NULL")
    again = _state(path)
    assert again.customers[2].vehicle.current_mileage == 60000
    assert _state(path).customers[2].vehicle.current_mileage == 60000


def test_existing_valid_saved_mileage_is_not_overwritten_by_seed(tmp_path):
    path = tmp_path / "d.db"
    _state(path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE customers SET current_mileage = 77777 WHERE vin = 'FIC00001'")
    assert _state(path).customers[0].vehicle.current_mileage == 77777


def test_old_schema_database_is_migrated_without_losing_rows(tmp_path):
    path = tmp_path / "d.db"
    state = _state(path)
    maya = _customer(state)
    state.schedule_appointment(maya.customer_name, date(2027, 2, 1), time(9, 0))
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE customers DROP COLUMN current_mileage")
        db.execute("ALTER TABLE appointments DROP COLUMN reason")
    reopened = _state(path)
    assert len(reopened.customers) == 20
    assert any(a.scheduled_date == date(2027, 2, 1) for a in reopened.appointments)


def test_recording_service_completes_matching_appointment_without_duplicates(tmp_path):
    path = tmp_path / "d.db"
    state = _state(path)
    maya = _customer(state)
    state.schedule_appointment(maya.customer_name, date(2027, 2, 1), time(9, 0), "Main Shop", "Tires")
    before = len(state.database.appointment_rows())
    state.record_service_visit(maya.customer_name, date(2027, 2, 1),
                               maya.vehicle.current_mileage + 10, "Main Shop")
    reopened = _state(path)
    rows = reopened.database.appointment_rows()
    assert len(rows) == before
    done = [a for a in reopened.appointments if a.scheduled_date == date(2027, 2, 1)]
    assert [a.status for a in done] == ["completed"]
    with sqlite3.connect(path) as db:
        link = db.execute("SELECT appointment_id FROM service_visits").fetchall()
    assert len(link) == 1 and link[0][0] is not None


def test_walk_in_visit_is_saved_without_an_appointment(tmp_path):
    path = tmp_path / "d.db"
    state = _state(path)
    maya = _customer(state)
    before = len(state.database.appointment_rows())
    state.record_service_visit(maya.customer_name, date(2027, 1, 15), 25000, "Express Shop",
                               "walk-in", None, "Lucas", "Oil")
    reopened = _state(path)
    assert len(reopened.database.appointment_rows()) == before
    assert reopened.customers[0].service_history[0].reason == "Oil"


def test_visits_and_appointments_stay_isolated_per_customer_and_dealership(tmp_path):
    path = tmp_path / "d.db"
    state = _state(path)
    chevy, kia = state.customers[0], state.customers[-1]
    assert chevy.dealership != kia.dealership
    state.schedule_appointment(chevy.customer_name, date(2027, 2, 1), time(9, 0))
    state.record_service_visit(kia.customer_name, date(2027, 2, 1), kia.vehicle.current_mileage + 5,
                               "Main Shop")
    reopened = _state(path)
    assert reopened.customers[0].service_history == ()
    assert len(reopened.customers[-1].service_history) == 1
    statuses = {a.vin: a.status for a in reopened.appointments if a.scheduled_date == date(2027, 2, 1)}
    assert statuses == {chevy.vehicle.vin: "scheduled"}


def test_in_memory_state_also_completes_appointment():
    state = DashboardState()
    maya = state.customers[0]
    state.schedule_appointment(maya.customer_name, date(2027, 2, 1), time(9, 0))
    state.record_service_visit(maya.customer_name, date(2027, 2, 1), 99999, "Main Shop")
    assert [a.status for a in state.appointments if a.scheduled_date == date(2027, 2, 1)] == ["completed"]
