import threading
from datetime import date
from http.client import HTTPConnection
from http.server import HTTPServer
from urllib.parse import parse_qs, urlencode

import pytest

from app.models.customer import CustomerLanguage
from app.models.holiday import HolidayCalendar, HolidayClosure
from app.models.outbox import OutboxStatus
from app.services.dashboard import DashboardState
from app.dashboard import DashboardHandler, _row, _single


def _dashboard() -> DashboardState:
    from dataclasses import replace

    from tests.unit.test_messaging import _customer, _customer_with_language

    english = _customer()
    spanish = replace(
        _customer_with_language(CustomerLanguage.SPANISH),
        customer_name="Spanish Customer",
        email="spanish@example.test",
    )
    return DashboardState(
        customers=(english, spanish),
        current_date=date(2025, 6, 1),
        holiday_calendars={
            "Kia": HolidayCalendar(
                "Kia",
                (HolidayClosure(date(2025, 4, 15), "Kia service holiday"),),
            )
        },
    )


def test_dashboard_filters_and_preserves_holiday_language_display_data():
    dashboard = _dashboard()

    spanish_rows = dashboard.rows(language=CustomerLanguage.SPANISH)

    assert len(spanish_rows) == 1
    row = spanish_rows[0]
    assert row.due is True
    assert row.deferred_to == date(2025, 4, 16)
    assert row.draft is not None
    assert row.draft.language_preference is CustomerLanguage.SPANISH
    assert "se pospone" in row.draft.body


def test_dashboard_approval_queue_and_simulated_send_flow():
    dashboard = _dashboard()

    dashboard.approve("Test Customer")
    queued = dashboard.queue("Test Customer")
    sent = dashboard.simulate_send("Test Customer")

    assert queued.status is OutboxStatus.QUEUED
    assert sent.status is OutboxStatus.SIMULATED_SENT
    assert sent.draft.status == "approved"
    assert dashboard.rows()[0].outbox.status is OutboxStatus.SIMULATED_SENT


def test_dashboard_rejection_requires_reason_and_blocks_queue():
    dashboard = _dashboard()

    with pytest.raises(ValueError, match="reason is required"):
        dashboard.reject("Test Customer", " ")

    rejected = dashboard.reject("Test Customer", "Needs correction")

    assert rejected.status == "rejected"
    with pytest.raises(ValueError, match="Only approved messages can be queued"):
        dashboard.queue("Test Customer")


def test_record_service_visit_clears_existing_workflow_state():
    dashboard = _dashboard()
    dashboard.approve("Test Customer")
    dashboard.queue("Test Customer")

    updated = dashboard.record_service_visit(
        "Test Customer",
        date(2025, 5, 31),
        2200,
        "Brake inspection",
    )

    row = dashboard.rows()[0]
    assert updated.service_history[-1].service_type == "Brake inspection"
    assert row.expected_date == date(2025, 8, 31)
    assert row.draft is None
    assert row.outbox is None


def test_post_form_action_values_are_decoded_as_strings():
    values = parse_qs(b"action=approve&customer_name=Test+Customer".decode("utf-8"))

    assert _single(values, "action") == "approve"
    assert _single(values, "customer_name") == "Test Customer"


CUSTOMER = "Fictional Customer 05"
FILTERS = "dealership=Chevrolet&agent=Cassandra&language=es"
RESET_FILTERS = "dealership=Chevrolet&agent=Tracy&language=en"


@pytest.fixture
def server():
    handler = type("TestHandler", (DashboardHandler,), {"state": DashboardState()})
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, handler.state
    httpd.shutdown()
    httpd.server_close()


def _request(httpd, method, path, body=""):
    connection = HTTPConnection("127.0.0.1", httpd.server_address[1])
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    connection.request(method, path, body=body or None, headers=headers)
    response = connection.getresponse()
    result = (response.status, response.getheader("Location"), response.read().decode())
    connection.close()
    return result


def _post(httpd, action, extra="", filters=FILTERS):
    body = urlencode({"customer_name": CUSTOMER, "action": action})
    return _request(httpd, "POST", "/", f"{body}&{extra}&{filters}")


def test_approve_redirect_preserves_filters(server):
    httpd, state = server

    status, location, _ = _post(httpd, "approve")

    assert (status, location) == (303, f"/?{FILTERS}")
    assert state.rows("Chevrolet", "Cassandra")[0].draft.status == "approved"


def test_reject_redirect_preserves_filters(server):
    httpd, state = server

    status, location, _ = _post(httpd, "reject", "reason=Needs+correction")

    assert (status, location) == (303, f"/?{FILTERS}")
    assert state.rows("Chevrolet", "Cassandra")[0].draft.status == "rejected"


def test_queue_redirect_preserves_filters(server):
    httpd, state = server
    _post(httpd, "approve")

    status, location, _ = _post(httpd, "queue")

    assert (status, location) == (303, f"/?{FILTERS}")
    assert state.outbox[0].status is OutboxStatus.QUEUED


def test_simulate_send_redirect_preserves_filters(server):
    httpd, state = server
    _post(httpd, "approve")
    _post(httpd, "queue")

    status, location, _ = _post(httpd, "send")

    assert (status, location) == (303, f"/?{FILTERS}")
    assert state.outbox[0].status is OutboxStatus.SIMULATED_SENT


def test_service_visit_post_updates_expected_date_and_preserves_filters(server):
    httpd, state = server
    body = urlencode(
        {
            "customer_name": CUSTOMER,
            "action": "service",
            "service_date": "2027-01-01",
            "mileage": "2200",
            "service_type": "Brake inspection",
            "notes": "Completed in shop",
            "dealership": "Chevrolet",
            "agent": "Cassandra",
            "language": "es",
        }
    )

    status, location, _ = _request(httpd, "POST", "/", body)

    assert (status, location) == (303, f"/?{FILTERS}")
    row = state.rows("Chevrolet", "Cassandra", CustomerLanguage.SPANISH)[0]
    assert row.expected_date == date(2027, 4, 1)
    assert row.draft is None
    _, _, html = _request(httpd, "GET", location)
    assert "Expected: 2027-04-01" in html
    assert 'value="service"' in html


def test_action_without_filters_redirects_to_root(server):
    httpd, _ = server

    assert _post(httpd, "approve", filters="")[:2] == (303, "/")


def test_invalid_filter_values_are_dropped_on_redirect(server):
    httpd, _ = server
    filters = urlencode(
        {"dealership": "Evil\r\nX: y", "agent": "Nobody", "language": "xx"}
    )

    assert _post(httpd, "approve", filters=filters)[:2] == (303, "/")


def test_invalid_language_keeps_valid_filters_on_redirect(server):
    httpd, _ = server

    filters = "dealership=Chevrolet&agent=Cassandra&language=bogus"

    assert _post(httpd, "approve", filters=filters)[:2] == (
        303,
        "/?dealership=Chevrolet&agent=Cassandra",
    )


def test_invalid_language_get_renders_page_instead_of_failing(server):
    httpd, _ = server

    status, _, html = _request(httpd, "GET", "/?language=bogus")

    assert status == 200
    assert CUSTOMER in html


def test_reset_clears_filters_and_returns_all_customers(server):
    httpd, _ = server

    status, _, filtered_html = _request(httpd, "GET", f"/?{RESET_FILTERS}")
    assert status == 200
    assert "Fictional Customer 02" in filtered_html
    assert "Fictional Customer 01" not in filtered_html

    reset_link = 'href="/">' 
    assert reset_link in filtered_html
    status, location, all_customers_html = _request(httpd, "GET", "/")

    assert status == 200
    assert location is None
    assert CUSTOMER in all_customers_html
    assert "Fictional Customer 01" in all_customers_html
    assert all_customers_html.count("<tr><td><strong>") == 20


def test_rendered_action_forms_include_hidden_filters(server):
    httpd, _ = server

    _, _, html = _request(httpd, "GET", f"/?{FILTERS}")

    assert CUSTOMER in html
    assert html.count('name="dealership" value="Chevrolet"') >= 2
    assert 'name="agent" value="Cassandra"' in html
    assert 'name="language" value="es"' in html
    assert 'value="approve">' + '<input type="hidden" name="dealership"' in html
    assert 'value="reject"><input type="hidden" name="dealership"' in html


def test_queue_form_includes_hidden_filters(server):
    httpd, _ = server
    _post(httpd, "approve")

    _, _, html = _request(httpd, "GET", f"/?{FILTERS}")

    assert 'value="queue"><input type="hidden" name="dealership"' in html


def test_queue_action_is_hidden_for_existing_outbox_and_available_for_other_customer():
    state = DashboardState()

    state.approve("Fictional Customer 05")
    state.queue("Fictional Customer 05")
    state.simulate_send("Fictional Customer 05")
    state.approve("Fictional Customer 10")

    rows = state.rows("Chevrolet", "Cassandra", CustomerLanguage.SPANISH)
    rendered = {
        row.customer.customer_name: _row(row)
        for row in rows
    }

    assert 'value="queue"' not in rendered["Fictional Customer 05"]
    assert 'value="queue"' in rendered["Fictional Customer 10"]
