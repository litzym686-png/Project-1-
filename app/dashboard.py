"""Run the local standard-library reminder workflow dashboard."""

from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import date
from urllib.parse import parse_qs, urlencode, urlparse

from app.models.customer import BDC_AGENTS, DEALERSHIPS, CustomerLanguage
from app.services.dashboard import DashboardState, demo_holiday_calendars


class DashboardHandler(BaseHTTPRequestHandler):
    """Render and mutate one in-memory dashboard state."""

    state = DashboardState(holiday_calendars=demo_holiday_calendars())

    def do_GET(self) -> None:
        """Render filtered dashboard rows."""
        query = parse_qs(urlparse(self.path).query)
        dealership, agent, language = _read_filters(query)
        rows = self.state.rows(dealership, agent, language)
        self._respond(_page(rows, dealership, agent, language))

    def do_POST(self) -> None:
        """Apply a workflow action and redirect back to the filtered dashboard."""
        body = self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8")
        values = parse_qs(body)
        try:
            self._apply_action(values)
            filters = _filter_query(*_read_filters(values))
            location = f"/?{filters}" if filters else "/"
            self._respond("", status=303, headers={"Location": location})
        except ValueError as error:
            self._respond(f"<h1>Action failed</h1><p>{escape(str(error))}</p>", status=400)

    def _apply_action(self, values: dict[str, list[str]]) -> None:
        """Dispatch one workflow action to the dashboard state."""
        action = _single(values, "action")
        customer_name = _single(values, "customer_name")
        if action == "approve":
            self.state.approve(customer_name)
        elif action == "reject":
            self.state.reject(customer_name, _single(values, "reason"))
        elif action == "queue":
            self.state.queue(customer_name)
        elif action == "send":
            self.state.simulate_send(customer_name)
        elif action == "service":
            self.state.record_service_visit(
                customer_name,
                date.fromisoformat(_single(values, "service_date")),
                int(_single(values, "mileage")),
                _single(values, "service_type"),
                _single(values, "notes") or None,
            )
        else:
            raise ValueError("Unknown dashboard action")

    def _respond(
        self,
        body: str,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Write a UTF-8 HTML response."""
        content = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)


def run_dashboard(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve the in-memory dashboard until interrupted."""
    server = HTTPServer((host, port), DashboardHandler)
    print(f"Dashboard running at http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _single(values: dict[str, list[str]], name: str) -> str:
    """Read one form value, defaulting to an empty string."""
    return values.get(name, [""])[0]


def _language(value: str) -> CustomerLanguage | None:
    """Convert a filter value into the typed language enum, ignoring unknown values."""
    try:
        return CustomerLanguage(value) if value else None
    except ValueError:
        return None


def _read_filters(values: dict[str, list[str]]):
    """Read dealership, agent, and language filters, dropping unknown values."""
    dealership = _single(values, "dealership")
    agent = _single(values, "agent")
    return (
        dealership if dealership in DEALERSHIPS else None,
        agent if agent in BDC_AGENTS else None,
        _language(_single(values, "language")),
    )


def _filter_pairs(dealership, agent, language) -> list[tuple[str, str]]:
    """Return the active filters as name/value pairs."""
    return [
        (key, value.value if isinstance(value, CustomerLanguage) else value)
        for key, value in (
            ("dealership", dealership),
            ("agent", agent),
            ("language", language),
        )
        if value
    ]


def _filter_query(dealership, agent, language) -> str:
    """Encode the active filters as a URL query string."""
    return urlencode(_filter_pairs(dealership, agent, language))


def _filter_fields(dealership, agent, language) -> str:
    """Render the active filters as hidden form inputs."""
    return "".join(
        f'<input type="hidden" name="{name}" value="{escape(value)}">'
        for name, value in _filter_pairs(dealership, agent, language)
    )


def _page(rows, dealership, agent, language) -> str:
    """Render the small presentation dashboard."""
    filters = _filter_query(dealership, agent, language)
    fields = _filter_fields(dealership, agent, language)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Service Reminder Demo</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f5f7fb; color: #182230; }}
header, form.filters, table {{ background: white; padding: 1rem; border-radius: .6rem; box-shadow: 0 2px 10px #172b4d18; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
th, td {{ padding: .65rem; border-bottom: 1px solid #e6e9ef; text-align: left; vertical-align: top; }}
th {{ color: #52606d; font-size: .85rem; }}
button {{ margin: .15rem; padding: .35rem .55rem; cursor: pointer; }}
.deferred {{ color: #925b00; font-weight: 600; }} .status {{ white-space: nowrap; }}
</style></head><body>
<header><h1>Service Reminder Demo</h1>
<p>In-memory only: review, approval, and simulated outbox actions never send real messages.</p></header>
<form class="filters" method="get">
<label>Dealership <select name="dealership"><option value="">All</option>
{_options(DEALERSHIPS, dealership)}</select></label>
<label>Agent <select name="agent"><option value="">All</option>
{_options(BDC_AGENTS, agent)}</select></label>
<label>Language <select name="language"><option value="">All</option>
{_options(CustomerLanguage, language)}</select></label>
<button>Filter</button> <a href="/">Reset</a>
</form>
<table><tr><th>Customer</th><th>Ownership</th><th>Due / holiday</th>
<th>Language / draft preview</th><th>Review / outbox</th></tr>
{"".join(_row(row, fields) for row in rows)}
</table></body></html>"""


def _options(values, selected) -> str:
    """Render select options for strings or enums."""
    return "".join(
        f'<option value="{escape(value.value if hasattr(value, "value") else value)}"'
        f'{" selected" if value == selected or getattr(value, "value", None) == selected else ""}>'
        f'{escape(value.value if hasattr(value, "value") else value)}</option>'
        for value in values
    )


def _row(row, fields: str = "") -> str:
    """Render one customer workflow row; fields are hidden filter inputs."""
    customer = row.customer
    draft = row.draft
    preview = escape(draft.body) if draft else "No draft: not due yet."
    holiday = (
        f'<span class="deferred">Deferred to {row.deferred_to.isoformat()} '
        f'({escape(row.closure_name)})</span>'
        if row.deferred_to
        else "Open calendar day"
    )
    actions = ""
    if draft and draft.status == "review_ready":
        actions = _action(customer.customer_name, "approve", "Approve", fields)
        actions += (
            f'<form method="post" style="display:inline"><input type="hidden" '
            f'name="customer_name" value="{escape(customer.customer_name)}">'
            f'<input type="hidden" name="action" value="reject">{fields}'
            '<input name="reason" placeholder="Rejection reason" required>'
            '<button>Reject</button></form>'
        )
    elif draft and draft.status == "approved" and row.outbox is None:
        actions = _action(customer.customer_name, "queue", "Queue", fields)
    if row.outbox and row.outbox.status.value == "queued":
        actions += _action(customer.customer_name, "send", "Simulate send", fields)
    actions += _service_form(customer.customer_name, fields)
    outbox = row.outbox.status.value if row.outbox else "not queued"
    return (
        f"<tr><td><strong>{escape(customer.customer_name)}</strong><br>"
        f"{escape(customer.email)}</td><td>{escape(customer.dealership)}<br>"
        f"Agent: {escape(customer.bdc_agent)}</td><td>{'Due' if row.due else 'Not due'}"
        f"<br>Expected: {row.expected_date.isoformat()}<br>{holiday}</td>"
        f"<td>{customer.language_preference.value}<br>{preview}</td>"
        f'<td class="status">Draft: {draft.status if draft else "none"}<br>'
        f"Outbox: {outbox}<br>{actions}</td></tr>"
    )


def _action(customer_name: str, action: str, label: str, fields: str = "") -> str:
    """Render a one-click POST action that keeps the active filters."""
    return (
        f'<form method="post" style="display:inline"><input type="hidden" '
        f'name="customer_name" value="{escape(customer_name)}">'
        f'<input type="hidden" name="action" value="{action}">{fields}'
        f"<button>{label}</button></form>"
    )


def _service_form(customer_name: str, fields: str) -> str:
    """Render the completed-service form for one customer."""
    return (
        f'<form method="post"><input type="hidden" name="customer_name" '
        f'value="{escape(customer_name)}"><input type="hidden" name="action" '
        f'value="service">{fields}<input type="date" name="service_date" '
        f'required><input type="number" name="mileage" min="0" '
        f'placeholder="Mileage" required><input name="service_type" '
        f'placeholder="Service type" required><input name="notes" '
        f'placeholder="Notes"><button>Record service</button></form>'
    )


if __name__ == "__main__":
    run_dashboard()
