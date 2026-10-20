import threading
from datetime import date, time
from http.client import HTTPConnection
from http.server import HTTPServer
from urllib.parse import parse_qs, urlencode

import pytest

from app.models.customer import CustomerLanguage
from app.models.holiday import HolidayCalendar, HolidayClosure
from app.data.seed_customers import FICTIONAL_CUSTOMERS
from app.models.outbox import OutboxStatus
from app.services.dashboard import DashboardState
from app.dashboard import (
    DashboardHandler,
    _page,
    _reports_page,
    _row,
    _service_center_page,
    _single,
)


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


def test_dashboard_rows_show_customer_and_ownership_data_only():
    dashboard = _dashboard()
    rendered = _row(dashboard.rows()[0])

    assert rendered.count("<td") == 2
    assert "<strong>Test Customer</strong>" in rendered
    assert "test@example.test" in rendered
    assert "555-010-99" in rendered
    assert "2024 Kia Sportage" in rendered
    assert "VIN: TEST1234" in rendered
    assert "Kia" in rendered
    assert "Agent: Lucas" in rendered
    assert "value=\"approve\"" not in rendered
    assert "value=\"reject\"" not in rendered
    assert "value=\"queue\"" not in rendered
    assert "value=\"send\"" not in rendered
    assert "value=\"service\"" not in rendered
    assert "Service date" not in rendered
    assert "Record service" not in rendered


def test_seed_contacts_render_for_all_twenty_customers():
    dashboard = DashboardState()
    html = _page(dashboard.rows(), None, None, None)
    contacts = (
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

    assert len(dashboard.rows()) == 20
    for name, email, phone in contacts:
        assert all(value in html for value in (name, email, phone))


def test_dashboard_redesign_keeps_navigation_overview_and_workflow_table():
    dashboard = _dashboard()
    html = _page(dashboard.rows(), None, None, None)

    assert all(
        label in html
        for label in ("Dashboard", "Service Center", "Appointments", "Reports", "Settings")
    )
    assert '<a href="/">Customers</a>' not in html
    assert "Overview" in html
    cards = [
        html.index(f'<div class="card-label">{label}</div>')
        for label in ("Total Customers", "Due for Service", "Needs Review", "Queued Messages")
    ]
    assert cards == sorted(cards)
    assert '<div class="card-label">Total Customers</div><div class="card-value">2' in html
    assert '<div class="card-label">Due for Service</div><div class="card-value">2' in html
    assert '<div class="card-label">Needs Review</div><div class="card-value">2' in html
    assert '<div class="card-label">Queued Messages</div><div class="card-value">0' in html
    assert html.count("<th>") == 2
    assert html.count("<tr><td><strong>") == 2
    assert "name=\"dealership\"" in html
    assert 'href="/">Reset</a>' in html


def test_dashboard_summary_agents_count_unique_across_unfiltered_dealerships():
    dashboard = DashboardState()
    html = _page(dashboard.rows(), None, None, None)

    assert '<div class="card-label">Total Customers</div><div class="card-value">20' in html
    assert '<div class="card-label">Due for Service</div><div class="card-value">20' in html
    assert '<div class="card-label">Needs Review</div><div class="card-value">20' in html
    assert '<div class="card-label">Queued Messages</div><div class="card-value">0' in html


def test_dashboard_summary_counts_follow_language_filter():
    dashboard = _dashboard()
    html = _page(dashboard.rows(language=CustomerLanguage.SPANISH), None, None, CustomerLanguage.SPANISH)

    assert '<div class="card-label">Total Customers</div><div class="card-value">1' in html
    assert '<div class="card-label">Due for Service</div><div class="card-value">1' in html
    assert '<div class="card-label">Needs Review</div><div class="card-value">1' in html
    assert '<div class="card-label">Queued Messages</div><div class="card-value">0' in html


def test_service_center_renders_navigation_selection_editor_and_service_form():
    dashboard = _dashboard()
    row = dashboard.rows()[0]
    rendered = _service_center_page(
        dashboard, (row,), "Kia", "Lucas", CustomerLanguage.ENGLISH, "Test Customer"
    )

    assert rendered.index('>Dashboard</a>') < rendered.index(
        'class="active" href="/service-center"'
    )
    assert 'class="active"' in rendered
    assert ">Service Center</a>" in rendered
    assert '<a href="/">Customers</a>' not in rendered
    assert "Selected Customer" in rendered
    assert "Test Customer" in rendered
    assert "message_body" in rendered
    assert "Save as Draft" in rendered
    assert "Send Message" in rendered
    assert '<label>Language<select name="message_language">' not in rendered
    assert 'name="message_language"\nvalue="en"' in rendered
    assert '<option>Main Shop</option><option>Express Shop</option>' in rendered
    assert '<select name="service_type" required>' in rendered
    assert 'name="description"' not in rendered
    assert 'name="notes"' in rendered
    assert "document.querySelector(\".history\")" in rendered
    assert 'name="technician"' in rendered
    assert "Record Service" in rendered


def test_reports_page_filters_completed_history_by_vehicle_and_customer():
    dashboard = _dashboard()
    dashboard.record_service_visit(
        "Test Customer", date(2025, 5, 1), 1200, "Inspection",
        description="Brake inspection", technician="Maya",
    )
    dashboard.record_service_visit(
        "Test Customer", date(2025, 6, 1), 1500, "Tire rotation",
        description="Rotated tires", technician="Maya",
    )

    html = _reports_page(
        dashboard,
        {"q": ["Sportage"], "dealership": ["Kia"], "customer": ["Test Customer"]},
    )

    assert "3 completed visits" in html
    assert html.index("Tire rotation") < html.index("Inspection") < html.index("Oil change")
    assert "Rotated tires" in html
    assert "Current mileage: 1,500 mi" in html
    assert "Last service: 2025-06-01" in html
    assert "Next expected service: " in html
    assert 'name="from"' not in html and 'name="to"' not in html
    assert "<label>From" not in html and "<label>To" not in html

    other = _reports_page(dashboard, {"dealership": ["Chevrolet"]})
    assert "Tire rotation" not in other


def test_reports_page_shows_selected_vehicle_header_and_empty_state():
    dashboard = _dashboard()
    html = _reports_page(dashboard, {"customer": ["Spanish Customer"]})

    assert "Spanish Customer" in html
    assert "VIN: " in html
    assert "Current mileage:" in html
    assert "Last service:" in html
    assert "Next expected service:" in html
    assert "No completed service visits have been recorded yet for this vehicle." in html


def test_reports_customer_selector_contains_all_seed_customers():
    html = _reports_page(DashboardState(), {})

    assert len(FICTIONAL_CUSTOMERS) == 20
    for customer in FICTIONAL_CUSTOMERS:
        assert f'value="{customer.customer_name}"' in html


def test_service_center_save_and_send_use_existing_simulated_workflow():
    dashboard = _dashboard()

    saved = dashboard.save_draft(
        "Test Customer",
        "Hola Test Customer, mensaje editado.",
        CustomerLanguage.SPANISH,
    )
    assert saved.status == "draft"
    assert saved.language_preference is CustomerLanguage.SPANISH

    sent = dashboard.send_message(
        "Test Customer",
        "Hola Test Customer, envio simulado.",
        CustomerLanguage.SPANISH,
    )

    assert sent.status is OutboxStatus.SIMULATED_SENT
    assert sent.draft.status == "approved"
    assert sent.draft.language_preference is CustomerLanguage.SPANISH
    assert sent.draft.body == "Hola Test Customer, envio simulado."


def test_service_center_message_language_uses_selected_customer_without_control():
    dashboard = _dashboard()
    row = dashboard.rows(language=CustomerLanguage.SPANISH)[0]
    rendered = _service_center_page(
        dashboard,
        (row,),
        row.customer.dealership,
        row.customer.bdc_agent,
        CustomerLanguage.SPANISH,
        row.customer.customer_name,
    )

    assert '<label>Language<select name="message_language">' not in rendered
    assert 'name="message_language"\nvalue="es"' in rendered
    assert "textarea" in rendered
    assert "Save as Draft" in rendered and "Send Message" in rendered


def test_appointments_calendar_and_schedule_existing_customer():
    dashboard = DashboardState()
    assert len(dashboard.appointments) == 3
    appointment = dashboard.schedule_appointment(
        "Maya Rodriguez", date(2027, 1, 10), time(14, 30)
    )

    assert appointment.vin == "FIC00001"
    assert appointment.is_demo is False
    assert any(item.customer_name == "Maya Rodriguez" for item in dashboard.appointments)


def test_appointments_page_has_views_filters_icons_and_existing_records():
    dashboard = DashboardState()
    from app.dashboard import _appointments_page

    html = _appointments_page(dashboard, None, None, parse_qs("date=2027-01-04"))

    assert "Appointments" in html
    assert all(label in html for label in ("Week", "Month", "List", "Previous", "Next", "Today"))
    assert "Schedule Appointment" in html
    assert html.count("Schedule Appointment") == 1
    assert html.index("Schedule Appointment") < html.index("Dealership")
    assert '<a class="button" href="/service-center">Schedule Appointment</a>' in html
    assert (
        'href="/service-center?dealership=Chevrolet&amp;agent=Lucas&amp;customer=Maya+Rodriguez"'
        in html
    )
    assert 'class="date-picker"' in html
    assert "January 2027" in html
    assert html.count("<div class=\"picker-weekdays\">") == 1
    assert html.count("<span>") >= 7
    assert 'aria-label="Previous month"' in html
    assert 'aria-label="Next month"' in html
    assert 'class="picker-arrow picker-prev"' in html
    assert 'class="picker-arrow picker-next"' in html
    assert 'data-picker-month="2027-01-01"' in html
    assert "renderMonth" in html
    assert "pickerMonth" in html
    assert "picker-clear" in html and ">Apply</button>" in html
    assert 'data-date="2027-01-04"' in html
    assert 'name="date" value="2027-01-04"' in html
    assert "addEventListener" in html
    assert 'name="appointment_date"' not in html
    assert 'name="appointment_time"' not in html
    assert '<section class="schedule"><h2>Schedule Appointment' not in html
    assert html.count("<svg class=\"nav-icon\"") == 5
    assert "FIC00001" in html
    assert "Maya Rodriguez" in html


def test_appointments_picker_preserves_selected_date_for_month_view():
    dashboard = DashboardState()
    from app.dashboard import _appointments_page

    html = _appointments_page(
        dashboard,
        "Chevrolet",
        "Lucas",
        parse_qs("view=month&date=2027-02-14"),
    )

    assert "February 2027" in html
    assert 'name="date" value="2027-02-14"' in html
    assert 'data-date="2027-02-14"' in html
    assert "view=month" in html
    assert "2027-02-01" in html

    navigated = _appointments_page(
        dashboard,
        "Chevrolet",
        "Lucas",
        parse_qs("view=month&date=2027-02-14&picker_month=2027-04-01"),
    )
    assert "April 2027" in navigated
    assert 'name="date" value="2027-02-14"' in navigated


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
    assert 'will be due for service around 2025-08-31' in row.draft.body
    assert row.outbox is None


def test_post_form_action_values_are_decoded_as_strings():
    values = parse_qs(b"action=approve&customer_name=Test+Customer".decode("utf-8"))

    assert _single(values, "action") == "approve"
    assert _single(values, "customer_name") == "Test Customer"


CUSTOMER = "Noah Anderson"
FILTERS = "dealership=Chevrolet&agent=Cassandra&language=es"
RESET_FILTERS = "dealership=Chevrolet&agent=Tracy&language=en"


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "test-user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-password")
    handler = type("TestHandler", (DashboardHandler,), {"state": DashboardState()})
    handler.sessions.clear()
    handler.sessions["test-session"] = "test-user"
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    httpd.test_cookie = "dashboard_session=test-session"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, handler.state
    httpd.shutdown()
    httpd.server_close()


def _request(httpd, method, path, body="", cookie=None):
    connection = HTTPConnection("127.0.0.1", httpd.server_address[1])
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    selected_cookie = getattr(httpd, "test_cookie", None) if cookie is None else cookie
    if selected_cookie:
        headers["Cookie"] = selected_cookie
    connection.request(method, path, body=body or None, headers=headers)
    response = connection.getresponse()
    result = (response.status, response.getheader("Location"), response.read().decode())
    connection.close()
    return result


def _request_with_headers(httpd, method, path, body="", cookie=""):
    connection = HTTPConnection("127.0.0.1", httpd.server_address[1])
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if cookie:
        headers["Cookie"] = cookie
    connection.request(method, path, body=body or None, headers=headers)
    response = connection.getresponse()
    result = (
        response.status,
        dict(response.getheaders()),
        response.read().decode(),
    )
    connection.close()
    return result


def _post(httpd, action, extra="", filters=FILTERS):
    body = urlencode({"customer_name": CUSTOMER, "action": action})
    return _request(httpd, "POST", "/", f"{body}&{extra}&{filters}")


def test_reports_link_and_route_serve_vehicle_service_history_page(server):
    httpd, _ = server
    _, _, dashboard_html = _request(httpd, "GET", "/")
    assert 'href="/reports"' in dashboard_html

    status, _, reports_html = _request(httpd, "GET", "/reports")
    assert status == 200
    assert "<title>Vehicle Service History</title>" in reports_html
    assert "<title>Vehicle Service History</title>" not in dashboard_html


def test_auth_login_logout_protects_routes_and_preserves_state(server):
    httpd, state = server
    delattr(httpd, "test_cookie")
    state.schedule_appointment("Maya Rodriguez", date(2027, 2, 10), time(13, 30))

    status, _, login_html = _request_with_headers(httpd, "GET", "/login")
    assert status == 200
    assert 'name="username"' in login_html
    assert 'name="password"' in login_html

    denied_status, denied_headers, _ = _request_with_headers(httpd, "GET", "/")
    assert denied_status == 303
    assert denied_headers["Location"] == "/login?next=%2F"
    assert "no-store" in denied_headers["Cache-Control"]
    for path in ("/service-center", "/appointments", "/reports", "/settings"):
        assert _request(httpd, "GET", path, cookie="")[0] == 303

    wrong_body = urlencode(
        {"username": "test-user", "password": "wrong-password", "next": "/"}
    )
    status, wrong_headers, wrong_html = _request_with_headers(
        httpd, "POST", "/login", wrong_body
    )
    assert status == 401
    assert "Login failed" in wrong_html
    assert "wrong-password" not in wrong_html
    assert "Set-Cookie" not in wrong_headers

    login_body = urlencode(
        {
            "username": "test-user",
            "password": "test-password",
            "next": "/appointments",
        }
    )
    status, headers, _ = _request_with_headers(httpd, "POST", "/login", login_body)
    assert status == 303
    assert headers["Location"] == "/appointments"
    cookie = headers["Set-Cookie"].split(";", 1)[0]

    status, _, appointments_html = _request_with_headers(
        httpd, "GET", "/appointments?date=2027-01-04", cookie=cookie
    )
    assert status == 200
    assert "Maya Rodriguez" in appointments_html
    status, _, settings_html = _request_with_headers(
        httpd, "GET", "/settings", cookie=cookie
    )
    assert status == 200
    assert "Logout" in settings_html

    status, headers, _ = _request_with_headers(httpd, "POST", "/logout", cookie=cookie)
    assert status == 303
    assert headers["Location"] == "/login"
    assert "Max-Age=0" in headers["Set-Cookie"]
    assert _request(httpd, "GET", "/", cookie=cookie)[0] == 303

    status, headers, _ = _request_with_headers(httpd, "POST", "/login", login_body)
    assert status == 303
    relogin_cookie = headers["Set-Cookie"].split(";", 1)[0]
    status, _, relogin_html = _request_with_headers(
        httpd, "GET", "/appointments?date=2027-01-04", cookie=relogin_cookie
    )
    assert status == 200
    assert "Maya Rodriguez" in relogin_html


def test_auth_reports_missing_process_configuration_until_environment_is_set(
    server, monkeypatch
):
    httpd, _ = server
    delattr(httpd, "test_cookie")
    monkeypatch.delenv("DASHBOARD_USERNAME")
    monkeypatch.delenv("DASHBOARD_PASSWORD")

    login_body = urlencode(
        {"username": "test-user", "password": "test-password", "next": "/"}
    )
    status, headers, html = _request_with_headers(httpd, "POST", "/login", login_body)
    assert status == 401
    assert "Authentication is not configured in this server process." in html
    assert "Set-Cookie" not in headers

    monkeypatch.setenv("DASHBOARD_USERNAME", "test-user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-password")
    status, headers, _ = _request_with_headers(httpd, "POST", "/login", login_body)
    assert status == 303
    assert headers["Location"] == "/"
    assert "Set-Cookie" in headers


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
            "service_type": "Express Shop",
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
    assert 'alrededor del 2027-04-01' in row.draft.body
    _, _, html = _request(httpd, "GET", location)
    assert CUSTOMER in html
    assert 'value="service"' not in html


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


def test_service_center_get_and_save_draft_preserve_filters(server):
    httpd, state = server
    query = "dealership=Kia&agent=Lucas&language=en&customer=Camila+Brooks"

    status, _, all_html = _request(httpd, "GET", "/service-center")

    assert status == 200
    assert '<option value="Maya Rodriguez" selected>Maya Rodriguez</option>' in all_html
    status, _, html = _request(httpd, "GET", f"/service-center?{query}")

    assert status == 200
    assert "Selected Customer" in html
    assert "Save as Draft" in html
    assert "Send Message" in html
    assert "Main Shop" in html and "Express" in html
    assert '<label>Customer <select name="customer">' in html
    assert '<option value="Maya Rodriguez">Maya Rodriguez</option>' not in html
    assert '<option value="Camila Brooks" selected>Camila Brooks</option>' in html
    assert "Camila Brooks" in html
    body = urlencode(
        {
            "action": "save_draft",
            "return_to": "service-center",
            "customer_name": "Camila Brooks",
            "message_body": "Hola, borrador editado.",
            "message_language": "es",
            "dealership": "Kia",
            "agent": "Lucas",
            "language": "en",
        }
    )
    status, location, _ = _request(httpd, "POST", "/service-center", body)

    assert status == 303
    assert location == "/service-center?dealership=Kia&agent=Lucas&language=en&customer=Camila+Brooks"
    assert state.rows("Kia", "Lucas")[0].draft.body == "Hola, borrador editado."
    send_body = urlencode(
        {
            "action": "send_message",
            "return_to": "service-center",
            "customer_name": "Camila Brooks",
            "message_body": "Hola, mensaje simulado.",
            "message_language": "es",
            "dealership": "Kia",
            "agent": "Lucas",
            "language": "en",
        }
    )
    status, location, _ = _request(httpd, "POST", "/service-center", send_body)

    assert status == 303
    assert location == "/service-center?dealership=Kia&agent=Lucas&language=en&customer=Camila+Brooks"
    assert state.rows("Kia", "Lucas")[0].outbox.status is OutboxStatus.SIMULATED_SENT


def test_service_center_message_history_is_per_customer_and_simulated(server):
    httpd, state = server
    _, _, empty = _request(httpd, "GET", "/service-center?customer=Camila+Brooks")
    assert "No message history yet." in empty
    for name, text, action in (
        ("Camila Brooks", "Borrador uno.", "save_draft"),
        ("Camila Brooks", "Mensaje enviado.", "send_message"),
    ):
        body = urlencode(
            {"action": action, "return_to": "service-center", "customer_name": name,
             "message_body": text, "message_language": "es"}
        )
        assert _request(httpd, "POST", "/service-center", body)[0] == 303

    _, _, camila = _request(httpd, "GET", "/service-center?customer=Camila+Brooks")
    assert "Borrador uno." in camila and "Mensaje enviado." in camila
    assert "Draft saved" in camila and "Simulated send" in camila
    assert "simulated, not a delivered SMS" in camila
    assert "No message history yet." not in camila
    assert [e.event for e in state.message_history("Camila Brooks")] == [
        "Draft saved", "Simulated send"
    ]

    _, _, maya = _request(httpd, "GET", "/service-center?customer=Maya+Rodriguez")
    assert "Borrador uno." not in maya and "Mensaje enviado." not in maya
    assert "No message history yet." in maya


def test_appointments_http_schedule_redirects_and_renders_existing_vin(server):
    httpd, state = server
    body = urlencode(
        {
            "action": "schedule_appointment",
            "return_to": "appointments",
            "customer_name": "Maya Rodriguez",
            "appointment_date": "2027-02-10",
            "appointment_time": "13:30",
            "dealership": "Chevrolet",
            "agent": "Lucas",
        }
    )

    status, location, _ = _request(httpd, "POST", "/appointments", body)

    assert status == 303
    assert location == "/appointments?dealership=Chevrolet&agent=Lucas"
    assert any(
        item.customer_name == "Maya Rodriguez"
        and item.scheduled_date == date(2027, 2, 10)
        for item in state.appointments
    )


def test_reset_clears_filters_and_returns_all_customers(server):
    httpd, _ = server

    status, _, filtered_html = _request(httpd, "GET", f"/?{RESET_FILTERS}")
    assert status == 200
    assert "Ethan Parker" in filtered_html
    assert "Maya Rodriguez" not in filtered_html

    reset_link = 'href="/">' 
    assert reset_link in filtered_html
    status, location, all_customers_html = _request(httpd, "GET", "/")

    assert status == 200
    assert location is None
    assert CUSTOMER in all_customers_html
    assert "Maya Rodriguez" in all_customers_html
    assert all_customers_html.count("<tr><td><strong>") == 20


def test_main_customer_rows_do_not_render_workflow_action_forms(server):
    httpd, _ = server

    _, _, html = _request(httpd, "GET", f"/?{FILTERS}")

    assert CUSTOMER in html
    assert html.count("<tr><td><strong>") == 2
    assert 'value="approve"' not in html
    assert 'value="reject"' not in html
    assert 'value="queue"' not in html
    assert 'value="send"' not in html
    assert 'value="service"' not in html


def test_send_message_and_reply_repeat_without_error_and_keep_filters(server):
    httpd, state = server
    extra = urlencode({"return_to": "service-center", "message_body": "Hello again", "message_language": "es"})
    for _ in range(3):
        status, location, _html = _post(httpd, "send_message", extra)
        assert status == 303
        assert location.startswith("/service-center?")
        assert "dealership=Chevrolet" in location and "agent=Cassandra" in location
        assert "language=es" in location and "customer=" in location
    for n in range(3):
        status, location, _html = _post(
            httpd, "simulate_reply", urlencode({"return_to": "service-center", "reply_body": f"Reply {n}"})
        )
        assert status == 303 and location.startswith("/service-center?")
    assert len(state.message_history(CUSTOMER)) == 6
    _, _, page = _request(httpd, "GET", location)
    assert "Reply 2" in page and "Action failed" not in page


def test_send_clears_composer_but_keeps_default_reminder_and_history(server):
    httpd, state = server
    name = next(r.customer.customer_name for r in state.rows() if r.draft)
    original = next(r.draft for r in state.rows() if r.customer.customer_name == name)
    query = urlencode({"customer": name})
    _, _, before = _request(httpd, "GET", f"/service-center?{query}")
    assert original.body.split("\n")[0][:20] in before

    body = urlencode({"customer_name": name, "action": "send_message", "return_to": "service-center",
                      "message_body": "Typed note", "message_language": "en"})
    status, location, _ = _request(httpd, "POST", "/", body)
    assert status == 303
    _, _, after = _request(httpd, "GET", location)
    assert 'name="message_body"\nrequired></textarea>' in after
    assert "Typed note" in after
    assert next(r.draft for r in state.rows() if r.customer.customer_name == name) == original

    state.composer_cleared.discard(name)
    state.save_draft(name, "Saved draft", CustomerLanguage.ENGLISH)
    _, _, page = _request(httpd, "GET", location)
    assert "Saved draft" in page


def test_service_type_is_limited_to_main_or_express_shop(server):
    httpd, state = server
    base = {"customer_name": CUSTOMER, "action": "service", "service_date": "2027-01-01", "mileage": "2300",
            "notes": "ok", "return_to": "service-center"}
    status, _, html = _request(httpd, "POST", "/", urlencode({**base, "service_type": "Oil change"}))
    assert status == 400 and "Main Shop or Express Shop" in html
    cust = [c for c in state.customers if c.customer_name == CUSTOMER][0]
    assert not any(e.service_type == "Oil change" for e in cust.service_history)
    for kind in ("Main Shop", "Express Shop"):
        status, _, _ = _request(httpd, "POST", "/", urlencode({**base, "service_type": kind}))
        assert status == 303
    cust = [c for c in state.customers if c.customer_name == CUSTOMER][0]
    assert cust.service_history[-1].service_type == "Express Shop"
    assert cust.service_history[-1].description is None


def test_service_center_prefills_mileage_and_schedules_then_reports_reason(server):
    httpd, state = server
    cust = [c for c in state.customers if c.customer_name == CUSTOMER][0]
    query = urlencode({"customer": CUSTOMER, "dealership": "Chevrolet", "agent": "Cassandra", "language": "es"})
    _, _, page = _request(httpd, "GET", f"/service-center?{query}")
    expected = f'name="mileage" min="0" step="1" value="{cust.vehicle.current_mileage}"'
    assert page.count(expected) == 2
    assert 'name="appointment_date"' in page

    base = {"customer_name": CUSTOMER, "return_to": "service-center", "mileage": "48000"}
    status, _, _ = _request(httpd, "POST", "/", urlencode({
        **base, "action": "schedule_appointment", "appointment_date": "2027-02-02",
        "appointment_time": "09:30", "service_type": "Main Shop", "reason": "Brake check"}))
    assert status == 303
    _, _, appts = _request(httpd, "GET", "/appointments?date=2027-02-02")
    assert "Brake check" in appts and "Main Shop" in appts and "48,000 mi" in appts and "Scheduled" in appts

    status, _, _ = _request(httpd, "POST", "/", urlencode({
        **base, "action": "service", "service_date": "2027-02-02", "service_type": "Main Shop",
        "technician": "Tracy", "reason": "Brake check", "notes": "Pads replaced"}))
    assert status == 303
    _, _, reports = _request(httpd, "GET", "/reports")
    assert "REASON FOR VISIT" in reports and "Brake check" in reports and "Pads replaced" in reports
    assert "48,000 mi" in reports and "Tracy" in reports


def test_invalid_mileage_and_service_type_on_schedule_are_rejected(server):
    httpd, _ = server
    body = {"customer_name": CUSTOMER, "action": "schedule_appointment", "appointment_date": "2027-02-02",
            "appointment_time": "09:30", "return_to": "service-center"}
    status, _, _ = _request(httpd, "POST", "/", urlencode({**body, "mileage": "-5"}))
    assert status == 400
    status, _, _ = _request(httpd, "POST", "/", urlencode({**body, "service_type": "Detail"}))
    assert status == 400


def test_calendar_defaults_to_today_and_navigation_stays_in_sync(server):
    from datetime import date, timedelta
    httpd, _ = server
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    _, _, html = _request(httpd, "GET", "/appointments")
    assert today.strftime("%a %b %d") in html
    assert f"view=week&date={monday.isoformat()}" in html
    assert 'href="/appointments">Today' in html
    for view in ("week", "month", "list"):
        _, _, page = _request(httpd, "GET", f"/appointments?view={view}")
        assert f"view={view}&date={(monday + timedelta(days=7)).isoformat()}" in page
        assert f"view={view}&date={(monday - timedelta(days=7)).isoformat()}" in page
    _, _, nxt = _request(httpd, "GET", f"/appointments?view=week&date={(monday + timedelta(days=7)).isoformat()}")
    assert (monday + timedelta(days=7)).strftime("%a %b %d") in nxt
    _, _, old = _request(httpd, "GET", "/appointments?date=2027-01-04")
    assert "Jan 04" in old


def test_new_appointment_date_defaults_to_today(server):
    from datetime import date
    httpd, _ = server
    query = urlencode({"customer": CUSTOMER, "dealership": "Chevrolet", "agent": "Cassandra", "language": "es"})
    _, _, page = _request(httpd, "GET", f"/service-center?{query}")
    assert f'name="appointment_date" value="{date.today().isoformat()}"' in page
