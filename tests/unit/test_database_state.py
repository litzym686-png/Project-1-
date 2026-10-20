from datetime import date, time

from app.data.seed_customers import FICTIONAL_CUSTOMERS
from app.models.service_history import ServiceHistoryEntry
from app.services.database import Database
from app.services.dashboard import DashboardState
from app.services.service_history_store import ServiceHistoryStore


def test_recorded_visit_survives_restart_and_updates_next_service(tmp_path):
    path = tmp_path / "dashboard.db"
    first = DashboardState(database=Database(path))
    maya = first.customers[0]
    first.record_service_visit(
        maya.customer_name, date(2027, 1, 10), maya.vehicle.current_mileage + 500,
        "Oil change", "n", "Changed oil", "Tracy", "Routine",
    )

    second = DashboardState(database=Database(path))
    restored = second.customers[0]
    entry = restored.service_history[0]
    assert (entry.service_type, entry.description, entry.technician, entry.reason, entry.notes) == (
        "Oil change", "Changed oil", "Tracy", "Routine", "n",
    )
    assert restored.last_service_date == date(2027, 1, 10)
    assert restored.vehicle.current_mileage == maya.vehicle.current_mileage + 500
    assert all(c.service_history == () for c in second.customers[1:])
    assert len(second.customers) == 20


def test_legacy_json_history_is_imported_once_and_kept(tmp_path):
    store = ServiceHistoryStore(tmp_path / "service-history.json")
    maya = FICTIONAL_CUSTOMERS[0]
    legacy = ServiceHistoryEntry(date(2025, 3, 1), 900, "Tire rotation", None, "Rotated", "Lucas")
    store.save(maya.vehicle.vin, (legacy,))
    unknown = ServiceHistoryEntry(date(2025, 3, 2), 10, "Other")
    store.save("ZZZZZZZZ", (unknown,))
    path = tmp_path / "dashboard.db"

    DashboardState(database=Database(path), history_store=store)
    again = DashboardState(database=Database(path), history_store=store)

    assert again.customers[0].service_history == (legacy,)
    assert store.path.exists() and "ZZZZZZZZ" in store.path.read_text()
    assert list((tmp_path / "backups").glob("service_history-*.json"))


def test_appointments_persist_link_to_customer_and_seed_demo_once(tmp_path):
    path = tmp_path / "dashboard.db"
    first = DashboardState(database=Database(path))
    assert len(first.appointments) == 3 and all(a.is_demo for a in first.appointments)
    kia = next(c for c in first.customers if c.dealership == "Kia")
    first.schedule_appointment(kia.customer_name, date(2027, 3, 1), time(14, 0))

    second = DashboardState(database=Database(path))
    saved = [a for a in second.appointments if not a.is_demo]
    assert len(second.appointments) == 4
    assert [(a.customer_name, a.vin, a.dealership, a.assigned_agent) for a in saved] == [
        (kia.customer_name, kia.vehicle.vin, "Kia", kia.bdc_agent)
    ]
    assert (saved[0].scheduled_date, saved[0].scheduled_time) == (date(2027, 3, 1), time(14, 0))


def test_messages_persist_with_direction_and_never_mix_customers(tmp_path):
    from app.models.customer import CustomerLanguage

    path = tmp_path / "dashboard.db"
    first = DashboardState(database=Database(path))
    a, b = first.customers[0], first.customers[-1]
    first.save_draft(a.customer_name, "Borrador", CustomerLanguage.SPANISH)
    first.send_message(a.customer_name, "Enviado", CustomerLanguage.SPANISH)
    first.simulate_reply(a.customer_name, "Gracias")

    second = DashboardState(database=Database(path))
    history = second.message_history(a.customer_name)
    assert [(m.direction, m.event, m.body) for m in history] == [
        ("outgoing", "Draft saved", "Borrador"),
        ("outgoing", "Simulated send", "Enviado"),
        ("incoming", "Demo reply", "Gracias"),
    ]
    assert history[-1].sender == a.customer_name and history[-1].simulated
    assert second.message_history(b.customer_name) == ()


def test_repeated_sends_and_replies_persist_in_order_and_stay_isolated(tmp_path):
    from app.models.customer import CustomerLanguage

    path = tmp_path / "dashboard.db"
    first = DashboardState(database=Database(path))
    a = first.customers[0]
    same_dealer = next(c for c in first.customers[1:] if c.dealership == a.dealership)
    other_dealer = next(c for c in first.customers if c.dealership != a.dealership)
    for i in range(3):
        first.send_message(a.customer_name, "Same text", CustomerLanguage.ENGLISH)
        first.send_message(a.customer_name, f"Different {i}", CustomerLanguage.ENGLISH)
        first.simulate_reply(a.customer_name, f"Reply {i}")
    first.send_message(same_dealer.customer_name, "Other", CustomerLanguage.ENGLISH)

    second = DashboardState(database=Database(path))
    history = second.message_history(a.customer_name)
    assert len(history) == 9
    assert [m.direction for m in history].count("incoming") == 3
    assert [m.timestamp for m in history] == sorted(m.timestamp for m in history)
    assert [m.body for m in history if m.direction == "incoming"] == ["Reply 0", "Reply 1", "Reply 2"]
    assert all(m.simulated and m.sender for m in history)
    assert [m.body for m in second.message_history(same_dealer.customer_name)] == ["Other"]
    assert second.message_history(other_dealer.customer_name) == ()
    rows = Database(path).message_rows(a.vehicle.vin)
    assert {r["dealership"] for r in rows} == {a.dealership}
    assert {r["customer_id"] for r in rows} == {Database(path).customer_id(a.vehicle.vin)}


def test_reminder_queue_still_rejects_duplicate_automated_reminders():
    import pytest

    state = DashboardState()
    name = next(r.customer.customer_name for r in state.rows() if r.draft)
    state.approve(name)
    state.queue(name)
    with pytest.raises(ValueError, match="already queued"):
        state.queue(name)


def test_legacy_visit_with_description_and_old_type_is_kept_and_listed_in_reports(tmp_path):
    path = tmp_path / "dashboard.db"
    state = DashboardState(database=Database(path))
    c = state.customers[0]
    state.record_service_visit(c.customer_name, date(2027, 1, 5), 5000, "Oil change", "n", "Old description", "Lucas", "Noise")
    reopened = DashboardState(database=Database(path))
    entry = reopened.customers[0].service_history[-1]
    assert (entry.service_type, entry.description, entry.notes) == ("Oil change", "Old description", "n")
