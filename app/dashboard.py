"""Run the local standard-library reminder workflow dashboard."""

import calendar
import hmac
import os
import secrets
from http.cookies import SimpleCookie
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlparse

from app.models.customer import BDC_AGENTS, DEALERSHIPS, CustomerLanguage
from app.services.customer_service import expected_service_date
from app.services.dashboard import DashboardState, demo_holiday_calendars
from app.services.database import Database
from app.services.service_history_store import ServiceHistoryStore

SERVICE_TYPES = ("Main Shop", "Express Shop")

class DashboardHandler(BaseHTTPRequestHandler):
    """Render and mutate one in-memory dashboard state."""

    # The server is single-threaded; drop idle browser connections so one can't block it.
    timeout = 10

    state = DashboardState(holiday_calendars=demo_holiday_calendars())
    sessions: dict[str, str] = {}
    session_cookie = "dashboard_session"

    def do_GET(self) -> None:
        """Render filtered dashboard rows."""
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            if self._authenticated():
                self._redirect("/")
            else:
                self._respond(_login_page(next_path=_safe_next(parse_qs(parsed.query).get("next", ["/"])[0])))
            return
        if not self._authenticated():
            self._redirect_login(parsed.path)
            return
        query = parse_qs(parsed.query)
        dealership, agent, language = _read_filters(query)
        rows = self.state.rows(dealership, agent, language)
        if parsed.path == "/appointments":
            self._respond(_appointments_page(self.state, dealership, agent, query))
            return
        if parsed.path == "/service-center":
            selected = _selected_customer(query, rows)
            self._respond(
                _service_center_page(
                    self.state, rows, dealership, agent, language, selected
                )
            )
        elif parsed.path == "/reports":
            self._respond(_reports_page(self.state, query))
        elif parsed.path == "/settings":
            self._respond(_settings_page())
        else:
            self._respond(_page(rows, dealership, agent, language))

    def do_POST(self) -> None:
        """Apply a workflow action and redirect back to the filtered dashboard."""
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
        values = parse_qs(body)
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            self._login(values)
            return
        if parsed.path == "/logout":
            self._logout()
            return
        if not self._authenticated():
            self._redirect_login(parsed.path)
            return
        try:
            self._apply_action(values)
            filters = _filter_query(*_read_filters(values))
            return_to = _single(values, "return_to")
            customer = _single(values, "customer_name")
            customer_query = (
                urlencode({"customer": customer})
                if return_to == "service-center" and customer
                else ""
            )
            query = "&".join(part for part in (filters, customer_query) if part)
            prefix = (
                "/service-center"
                if return_to == "service-center"
                else "/appointments"
                if return_to == "appointments"
                else "/"
            )
            location = f"{prefix}?{query}" if query else prefix
            self._respond("", status=303, headers={"Location": location})
        except ValueError as error:
            self._respond(f"<h1>Action failed</h1><p>{escape(str(error))}</p>", status=400)

    def _authenticated(self) -> bool:
        """Return whether the request has a valid server-side session."""
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie.get(self.session_cookie)
        return bool(token and token.value in self.sessions)

    def _login(self, values: dict[str, list[str]]) -> None:
        """Authenticate configured local-demo credentials and create a session."""
        username = _single(values, "username")
        password = _single(values, "password")
        configured_user, configured_password = _configured_credentials()
        if not configured_user or not configured_password:
            message = "Authentication is not configured in this server process."
        elif not (
            hmac.compare_digest(username, configured_user)
            and hmac.compare_digest(password, configured_password)
        ):
            message = "Login failed. Check the configured credentials."
        else:
            message = ""
        if message:
            self._respond(
                _login_page(message, _safe_next(_single(values, "next"))),
                status=401,
            )
            return
        token = secrets.token_urlsafe(32)
        self.sessions[token] = username
        self._respond(
            "",
            status=303,
            headers={
                "Location": _safe_next(_single(values, "next")),
                "Set-Cookie": (
                    f"{self.session_cookie}={token}; Path=/; HttpOnly; SameSite=Lax"
                ),
            },
        )

    def _logout(self) -> None:
        """Invalidate the current server-side session and redirect to login."""
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie.get(self.session_cookie)
        if token:
            self.sessions.pop(token.value, None)
        self._respond(
            "",
            status=303,
            headers={
                "Location": "/login",
                "Set-Cookie": (
                    f"{self.session_cookie}=; Path=/; Max-Age=0; "
                    "HttpOnly; SameSite=Lax"
                ),
            },
        )

    def _redirect_login(self, path: str) -> None:
        """Redirect an unauthenticated request to the local login page."""
        next_path = path if path.startswith("/") and not path.startswith("//") else "/"
        self._redirect(f"/login?{urlencode({'next': next_path})}")

    def _redirect(self, location: str) -> None:
        """Send a no-cache redirect response."""
        self._respond("", status=303, headers={"Location": location})

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
        elif action == "save_draft":
            self.state.save_draft(
                customer_name,
                _single(values, "message_body"),
                _language(_single(values, "message_language"))
                or CustomerLanguage.ENGLISH,
            )
        elif action == "send_message":
            self.state.send_message(
                customer_name,
                _single(values, "message_body"),
                _language(_single(values, "message_language"))
                or CustomerLanguage.ENGLISH,
            )
        elif action == "simulate_reply":
            self.state.simulate_reply(customer_name, _single(values, "reply_body"))
        elif action == "service":
            service_type = _single(values, "service_type")
            if service_type not in SERVICE_TYPES:
                raise ValueError("Service type must be Main Shop or Express Shop")
            self.state.record_service_visit(
                customer_name,
                date.fromisoformat(_single(values, "service_date")),
                _single(values, "mileage"),
                service_type,
                _single(values, "notes") or None,
                None,
                _single(values, "technician") or None,
                _single(values, "reason") or None,
            )
        elif action == "schedule_appointment":
            service_type = _single(values, "service_type")
            if service_type and service_type not in SERVICE_TYPES:
                raise ValueError("Service type must be Main Shop or Express Shop")
            self.state.schedule_appointment(
                customer_name,
                date.fromisoformat(_single(values, "appointment_date")),
                datetime.strptime(
                    _single(values, "appointment_time"), "%H:%M"
                ).time(),
                service_type or None,
                _single(values, "reason") or None,
                _single(values, "mileage") or None,
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
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Vary", "Cookie")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)


def run_dashboard(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve the dashboard, backed by the local SQLite database, until interrupted."""
    DashboardHandler.state = DashboardState(
        holiday_calendars=demo_holiday_calendars(),
        history_store=ServiceHistoryStore(),
        database=Database(),
    )
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


def _safe_next(value: str) -> str:
    """Allow only local absolute paths for post-login redirects."""
    return value if value.startswith("/") and not value.startswith("//") else "/"


def _configured_credentials() -> tuple[str | None, str | None]:
    """Read credentials from the environment of this running server process."""
    return (
        os.environ.get("DASHBOARD_USERNAME"),
        os.environ.get("DASHBOARD_PASSWORD"),
    )


def _login_page(message: str = "", next_path: str = "/") -> str:
    """Render the local-demo login form without embedding credentials."""
    notice = f'<p class="error">{escape(message)}</p>' if message else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Login</title>
<style>body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; font-family: system-ui, sans-serif; background: #f6f5fb; color: #182230; }}
.login {{ width: min(24rem, calc(100% - 2rem)); background: white; border: 1px solid #ebe7f4; border-radius: .7rem; padding: 1.5rem; box-shadow: 0 8px 24px #32145f22; }}
h1 {{ margin-top: 0; color: #32145f; }} label {{ display: grid; gap: .3rem; margin: .8rem 0; color: #52606d; }}
input, button {{ width: 100%; box-sizing: border-box; padding: .6rem; border-radius: .35rem; border: 1px solid #d7d0e5; }}
button {{ border: 0; background: #5b2aa0; color: white; cursor: pointer; }} .muted {{ color: #667085; font-size: .9rem; }}
.error {{ color: #a33a3a; }}</style></head><body><main class="login"><h1>Service Center Login</h1>
<p class="muted">Configure DASHBOARD_USERNAME and DASHBOARD_PASSWORD before starting or restarting the local demo.</p>{notice}
<form method="post" action="/login"><input type="hidden" name="next" value="{escape(_safe_next(next_path))}">
<label>Username<input name="username" autocomplete="username" required></label>
<label>Password<input type="password" name="password" autocomplete="current-password" required></label>
<button>Log in</button></form></main></body></html>"""


def _settings_page() -> str:
    """Render settings with the session logout control."""
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Settings</title>
<style>
* { box-sizing: border-box; } body { margin: 0; font-family: system-ui, sans-serif; background: #f6f5fb; color: #182230; }
.app { display: flex; min-height: 100vh; } .sidebar { width: 230px; flex: 0 0 230px; padding: 1.5rem 1rem; background: #32145f; color: white; }
.brand { font-size: 1.2rem; font-weight: 700; margin: 0 0 2rem; } .nav { display: grid; gap: .35rem; }
.nav a { color: #e8ddff; padding: .7rem .8rem; border-radius: .45rem; text-decoration: none; }
.nav a.active, .nav a:hover { background: #5b2aa0; color: white; } .nav-icon { width: 1rem; height: 1rem; margin-right: .55rem; vertical-align: -0.15rem; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.main { width: 100%; padding: 2rem 2.5rem; } .panel { max-width: 38rem; background: white; border: 1px solid #ebe7f4; border-radius: .7rem; padding: 1.2rem; }
h1 { color: #281047; } button { border: 0; border-radius: .35rem; padding: .55rem .8rem; background: #5b2aa0; color: white; cursor: pointer; }
</style></head><body><div class="app"><aside class="sidebar"><p class="brand">Service Center</p>
<nav class="nav" aria-label="Main navigation">""" + _nav("/settings") + """</nav></aside>
<main class="main"><h1>Settings</h1><section class="panel"><h2>Session</h2>
<p>Manage the current local-demo session.</p><form method="post" action="/logout">
<button>Logout</button></form></section></main></div></body></html>"""


def _nav(active: str) -> str:
    """Render consistent inline-SVG navigation links."""
    links = (
        ("/", "Dashboard", "grid"),
        ("/service-center", "Service Center", "user"),
        ("/appointments", "Appointments", "calendar"),
        ("/reports", "Reports", "chart"),
        ("/settings", "Settings", "gear"),
    )
    return "".join(
        f'<a class="{"active" if path == active else ""}" href="{path}">'
        f'{_icon(icon)}{label}</a>'
        for path, label, icon in links
    )


def _icon(name: str) -> str:
    """Return a small accessible inline SVG icon."""
    paths = {
        "grid": '<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/>',
        "user": '<circle cx="12" cy="8" r="3"/><path d="M5 20a7 7 0 0 1 14 0"/>',
        "calendar": '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/>',
        "chart": '<path d="M5 19V9M12 19V5M19 19v-7"/>',
        "gear": '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.5-2.3 1a7 7 0 0 0-1.7-1L14.5 3h-5L9 6a7 7 0 0 0-1.7 1L5 6 3 9.5 5 11a7 7 0 0 0 0 2l-2 1.5L5 18l2.3-1a7 7 0 0 0 1.7 1l.5 3h5l.5-3a7 7 0 0 0 1.7-1l2.3 1 2-3.5-2-1.5a7 7 0 0 0 .1-1z"/>',
    }
    return f'<svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>'


def _selected_customer(values, rows):
    """Select a filtered customer by name, defaulting to the first row."""
    requested = _single(values, "customer")
    names = {row.customer.customer_name for row in rows}
    if requested in names:
        return requested
    return rows[0].customer.customer_name if rows else None


def _page(rows, dealership, agent, language) -> str:
    """Render the presentation dashboard around the existing workflow table."""
    fields = _filter_fields(dealership, agent, language)
    summary = _summary_cards(rows)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width, initial-scale=1"><title>Service Reminder Dashboard</title>
<style>
* {{ box-sizing: border-box; }} body {{ margin: 0; font-family: system-ui, sans-serif;
background: #f6f5fb; color: #182230; }} .app {{ display: flex; min-height: 100vh; }}
.sidebar {{ width: 230px; flex: 0 0 230px; padding: 1.5rem 1rem; background: #32145f;
color: white; }} .brand {{ font-size: 1.2rem; font-weight: 700; margin: 0 0 2rem; }}
.nav {{ display: grid; gap: .35rem; }} .nav a {{ color: #e8ddff; padding: .7rem .8rem;
border-radius: .45rem; text-decoration: none; }} .nav a.active, .nav a:hover {{ background: #5b2aa0;
color: white; }} .nav-icon {{ width: 1rem; height: 1rem; margin-right: .55rem; vertical-align: -0.15rem;
fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }}
.main {{ width: 100%; padding: 2rem 2.5rem; }} .topbar {{ display: flex;
justify-content: space-between; align-items: center; gap: 1rem; margin-bottom: 1.5rem; }}
h1 {{ margin: 0; color: #281047; }} .muted {{ color: #667085; }} .summary {{ display: grid;
grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }}
.card, form.filters, table {{ background: white; border: 1px solid #ebe7f4; border-radius: .7rem;
box-shadow: 0 3px 12px #32145f12; }} .card {{ padding: .9rem; }} .card-label {{ color: #667085;
font-size: .85rem; }} .card-value {{ color: #32145f; font-size: 1.8rem; font-weight: 700; margin-top: .35rem; }}
.overview, form.filters {{ padding: 1rem; margin-bottom: 1rem; }} .overview h2 {{ margin: 0 0 .35rem; }}
form.filters {{ display: flex; flex-wrap: wrap; align-items: end; gap: .7rem; }} label {{ display: grid;
gap: .25rem; color: #52606d; font-size: .85rem; }} select, input {{ padding: .45rem; border: 1px solid #d7d0e5;
border-radius: .35rem; }} button {{ margin: .15rem; padding: .45rem .7rem; cursor: pointer; border: 0;
border-radius: .35rem; background: #5b2aa0; color: white; }} form.filters button {{ background: #32145f; }}
table {{ width: 100%; border-collapse: separate; border-spacing: 0; overflow: hidden; }} th, td {{ padding: .7rem;
border-bottom: 1px solid #e6e9ef; text-align: left; vertical-align: top; }} th {{ background: #faf9fd;
color: #52606d; font-size: .78rem; letter-spacing: .04em; }} tr:last-child td {{ border-bottom: 0; }}
td small {{ color: #52606d; display: block; line-height: 1.45; }} .deferred {{ color: #925b00; font-weight: 600; }}
.status {{ white-space: nowrap; }} .preview-box {{ margin-top: .35rem; padding: .5rem; background: #faf9fd;
border: 1px solid #ebe7f4; border-radius: .4rem; }} .language-badge {{ display: inline-block; margin-right: .35rem;
padding: .12rem .35rem; border-radius: .3rem; background: #eadcff; color: #4a2087; font-size: .7rem;
font-weight: 700; }} details {{ display: inline; }} summary {{ display: inline; cursor: pointer; color: #5b2aa0;
font-size: .82rem; }} .message-body {{ margin-top: .45rem; color: #344054; white-space: normal; }}
.control-row {{ display: flex; flex-wrap: wrap; align-items: center; gap: .35rem; margin-top: .35rem; }}
.service-form {{ margin-top: .35rem; }} .service-row {{ display: flex; gap: .35rem; margin-top: .3rem; }}
.service-row label {{ flex: 1 1 0; min-width: 7rem; }} .service-form input {{ width: 100%; }}
.status button {{ white-space: nowrap; }} @media (max-width: 850px) {{ .app {{ display: block; }} .sidebar {{ width: 100%;
padding: 1rem; }} .brand {{ margin-bottom: .8rem; }} .nav {{ grid-template-columns: repeat(5, minmax(0, 1fr)); }}
.nav a {{ font-size: .75rem; text-align: center; padding: .55rem .2rem; }} .main {{ padding: 1.2rem; }}
.summary {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} table {{ display: block; overflow-x: auto; }} }}
</style></head><body>
<div class="app"><aside class="sidebar"><p class="brand">Service Center</p>
<nav class="nav" aria-label="Main navigation">{_nav("/")}</nav>
</aside><main class="main"><div class="topbar"><div><h1>Dashboard</h1>
<p class="muted">Service reminders, review, and simulated delivery.</p></div>
<span class="muted">In-memory demo</span></div>
<section class="summary" aria-label="Overview summary">{summary}</section>
<section class="overview"><h2>Overview</h2><p class="muted">Track due customers and manage
language-aware reminders without sending real messages or calling external services.</p></section>
<form class="filters" method="get">
<label>Dealership <select name="dealership"><option value="">All</option>
{_options(DEALERSHIPS, dealership)}</select></label>
<label>Agent <select name="agent"><option value="">All</option>
{_options(BDC_AGENTS, agent)}</select></label>
<label>Language <select name="language"><option value="">All</option>
{_options(CustomerLanguage, language)}</select></label>
<button>Filter</button> <a href="/">Reset</a>
</form>
<table><tr><th>CUSTOMER</th><th>OWNERSHIP</th></tr>
{"".join(_row(row, fields) for row in rows)}
</table></main></div></body></html>"""


def _summary_cards(rows) -> str:
    """Render real-data overview counts for the currently visible rows."""
    due = sum(row.due for row in rows)
    review = sum(bool(row.draft and row.draft.status == "review_ready") for row in rows)
    queued = sum(bool(row.outbox and row.outbox.status.value == "queued") for row in rows)
    return "".join(
        f'<article class="card"><div class="card-label">{label}</div>'
        f'<div class="card-value">{value}</div></article>'
        for label, value in (
            ("Total Customers", len(rows)),
            ("Due for Service", due),
            ("Needs Review", review),
            ("Queued Messages", queued),
        )
    )


def _reports_page(state: DashboardState, query) -> str:
    """Render the persistent completed vehicle service history."""
    search = _single(query, "q").strip()
    dealership = _single(query, "dealership")
    customer_name = _single(query, "customer")
    visits = tuple(
        (customer, entry)
        for customer, entry in state.service_history()
        if _history_matches(customer, entry, search, dealership, customer_name)
    )
    rows = "".join(_history_row(customer, entry) for customer, entry in visits)
    customer_options = "".join(
        f'<option value="{escape(customer.customer_name)}"'
        f'{" selected" if customer.customer_name == customer_name else ""}>'
        f'{escape(customer.customer_name)}</option>'
        for customer in state.customers
    )
    selected_customer = next(
        (customer for customer in state.customers if customer.customer_name == customer_name),
        None,
    )
    vehicle_header = ""
    if selected_customer:
        vehicle = selected_customer.vehicle
        next_date = expected_service_date(selected_customer)
        vehicle_header = (
            f'<section class="vehicle-header"><strong>{escape(selected_customer.customer_name)}</strong>'
            f'<span>{escape(selected_customer.dealership)}</span>'
            f'<span>{vehicle.year} {escape(vehicle.make)} {escape(vehicle.model)}</span>'
            f'<span>VIN: {escape(vehicle.vin)}</span>'
            f'<span>Current mileage: {vehicle.current_mileage:,} mi</span>'
            f'<span>Last service: {selected_customer.last_service_date.isoformat()}</span>'
            f'<span>Next expected service: {next_date.isoformat()}</span></section>'
        )
    empty_message = (
        "No completed service visits have been recorded yet for this vehicle."
        if selected_customer
        else "No completed service visits match these filters."
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Vehicle Service History</title>
<style>
* {{ box-sizing: border-box; }} body {{ margin: 0; font-family: system-ui, sans-serif;
background: #f6f5fb; color: #182230; }} .app {{ display: flex; min-height: 100vh; }}
.sidebar {{ width: 230px; flex: 0 0 230px; padding: 1.5rem 1rem; background: #32145f; color: white; }}
.brand {{ font-size: 1.2rem; font-weight: 700; margin: 0 0 2rem; }} .nav {{ display: grid; gap: .35rem; }}
.nav a {{ color: #e8ddff; padding: .7rem .8rem; border-radius: .45rem; text-decoration: none; }}
.nav a.active, .nav a:hover {{ background: #5b2aa0; color: white; }} .nav-icon {{ width: 1rem;
height: 1rem; margin-right: .55rem; vertical-align: -0.15rem; fill: none; stroke: currentColor;
stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }} .main {{ width: 100%; padding: 2rem 2.5rem; }}
h1 {{ margin: 0; color: #281047; }} .muted {{ color: #667085; }} .filters {{ display: flex;
flex-wrap: wrap; align-items: end; gap: .7rem; padding: 1rem; margin: 1rem 0;
background: white; border: 1px solid #ebe7f4; border-radius: .7rem; }} label {{ display: grid;
gap: .25rem; color: #52606d; font-size: .85rem; flex: 1 1 11rem; }} input, select {{ padding: .45rem;
border: 1px solid #d7d0e5; border-radius: .35rem; }} button, .reset {{ padding: .5rem .75rem;
border: 0; border-radius: .35rem; background: #5b2aa0; color: white; text-decoration: none; cursor: pointer; }}
.reset {{ background: #eef1f6; color: #344054; }} table {{ width: 100%; border-collapse: separate;
border-spacing: 0; overflow: hidden; background: white; border: 1px solid #ebe7f4;
border-radius: .7rem; box-shadow: 0 3px 12px #32145f12; }} th, td {{ padding: .7rem;
border-bottom: 1px solid #e6e9ef; text-align: left; vertical-align: top; }} th {{ background: #faf9fd;
color: #52606d; font-size: .78rem; letter-spacing: .04em; }} tr:last-child td {{ border-bottom: 0; }}
td small {{ display: block; margin-top: .2rem; color: #667085; line-height: 1.4; }}
.vehicle-header {{ display: flex; flex-wrap: wrap; gap: .5rem 1rem; align-items: baseline;
padding: 1rem; margin: 1rem 0; background: linear-gradient(100deg, #eef7ff, #f1ebff);
border-left: 4px solid #3b82f6; border-radius: .55rem; }} .vehicle-header span {{ color: #52606d; }}
@media (max-width: 850px) {{ .app {{ display: block; }} .sidebar {{ width: 100%; padding: 1rem; }}
.nav {{ grid-template-columns: repeat(5, minmax(0, 1fr)); }} .nav a {{ font-size: .75rem;
text-align: center; padding: .55rem .2rem; }} .main {{ padding: 1.2rem; }} table {{ display: block; overflow-x: auto; }} }}
</style></head><body><div class="app"><aside class="sidebar"><p class="brand">Service Center</p>
<nav class="nav" aria-label="Main navigation">{_nav("/reports")}</nav></aside><main class="main">
<h1>Vehicle Service History</h1><p class="muted">Completed visits only; drafts and simulated messages are not service records.</p>
<form class="filters" method="get"><label>Search customer, vehicle, or VIN
<input name="q" value="{escape(search)}" placeholder="Search history"></label>
<label>Dealership<select name="dealership"><option value="">All</option>{_options(DEALERSHIPS, dealership)}</select></label>
<label>Customer<select name="customer"><option value="">All</option>{customer_options}</select></label>
<button>Filter</button><a class="reset" href="/reports">Reset filters</a></form>
<p class="muted">{len(visits)} completed visit{"s" if len(visits) != 1 else ""}. Reset filters never deletes recorded history.</p>
{vehicle_header}
{f'<table><thead><tr><th>CUSTOMER / DEALERSHIP</th><th>VEHICLE</th><th>SERVICE DATE</th><th>SERVICE</th><th>REASON FOR VISIT</th><th>TECHNICIAN</th><th>NOTES</th></tr></thead><tbody>{rows}</tbody></table>' if rows else '<section class="filters"><p>' + escape(empty_message) + '</p></section>'}
</main></div></body></html>"""


def _history_matches(
    customer,
    entry,
    search: str,
    dealership: str,
    customer_name: str,
) -> bool:
    """Apply report search and filter criteria to one completed visit."""
    haystack = " ".join(
        (customer.customer_name, customer.vehicle.make, customer.vehicle.model, customer.vehicle.vin)
    ).lower()
    return (
        (not search or search.lower() in haystack)
        and (not dealership or customer.dealership == dealership)
        and (not customer_name or customer.customer_name == customer_name)
    )


def _history_row(customer, entry) -> str:
    """Render one completed visit with all requested history details."""
    vehicle = f"{customer.vehicle.year} {customer.vehicle.make} {customer.vehicle.model}"
    notes = entry.notes or "No notes"
    description = f"<small>{escape(entry.description)}</small>" if entry.description else ""
    technician = entry.technician or customer.bdc_agent
    return (
        f"<tr><td><strong>{escape(customer.customer_name)}</strong>"
        f"<small>{escape(customer.dealership)}</small></td>"
        f"<td>{escape(vehicle)}<small>VIN: {escape(customer.vehicle.vin)}</small></td>"
        f"<td>{entry.service_date.isoformat()}<small>{entry.mileage:,} mi</small></td>"
        f"<td><strong>{escape(entry.service_type)}</strong>"
        f"{description}</td>"
        f"<td>{escape(entry.reason or 'Not recorded')}</td>"
        f"<td>{escape(technician)}</td><td>{escape(notes)}</td></tr>"
    )


def _appointments_page(state, dealership, agent, query) -> str:
    """Render the weekly appointments calendar and scheduling form."""
    appointments = tuple(
        appointment
        for appointment in state.appointments
        if (not dealership or appointment.dealership == dealership)
        and (not agent or appointment.assigned_agent == agent)
    )
    view = _single(query, "view") or "week"
    selected_date = date.fromisoformat(_single(query, "date") or "2027-01-04")
    anchor = selected_date
    monday = anchor - timedelta(days=anchor.weekday())
    picker_month = date.fromisoformat(
        _single(query, "picker_month") or selected_date.replace(day=1).isoformat()
    ).replace(day=1)
    days = tuple(monday + timedelta(days=index) for index in range(7))
    cards = "".join(
        _appointment_card(appointment)
        for appointment in appointments
        if view != "week" or appointment.scheduled_date in days
    )
    if view == "month":
        calendar = _appointment_month(appointments, monday)
    elif view == "list":
        calendar = f'<div class="appointment-list">{cards or "<p>No appointments.</p>"}</div>'
    else:
        calendar = _appointment_week(appointments, days)
    service_center_query = urlencode(
        {
            key: value
            for key, value in (("dealership", dealership), ("agent", agent))
            if value
        }
    )
    service_center_href = "/service-center"
    if service_center_query:
        service_center_href += f"?{service_center_query}"
    picker = _date_picker_markup(
        selected_date, picker_month, view, dealership, agent
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Appointments</title>
<style>
* {{ box-sizing: border-box; }} body {{ margin: 0; font-family: system-ui, sans-serif; background: #f6f5fb; color: #182230; }}
.app {{ display: flex; min-height: 100vh; }} .sidebar {{ width: 230px; flex: 0 0 230px; padding: 1.5rem 1rem; background: #32145f; color: white; }}
.brand {{ font-size: 1.2rem; font-weight: 700; margin: 0 0 2rem; }} .nav {{ display: grid; gap: .35rem; }}
.nav a {{ color: #e8ddff; padding: .7rem .8rem; border-radius: .45rem; text-decoration: none; }}
.nav a.active, .nav a:hover {{ background: #5b2aa0; color: white; }} .nav-icon {{ width: 1rem; height: 1rem; margin-right: .55rem; vertical-align: -0.15rem; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }}
.main {{ width: 100%; padding: 2rem 2.5rem; }} .page-heading {{ display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; }} h1 {{ margin: 0; color: #281047; }} .muted {{ color: #667085; }}
.toolbar, .schedule {{ background: white; border: 1px solid #ebe7f4; border-radius: .7rem; padding: 1rem; margin-bottom: 1rem; }}
.toolbar {{ display: flex; flex-wrap: wrap; gap: .7rem; align-items: end; }} label {{ display: grid; gap: .25rem; color: #52606d; font-size: .85rem; }} .date-picker {{ position: relative; align-self: end; }}
.date-picker summary {{ cursor: pointer; list-style: none; padding: .45rem .6rem; border: 1px solid #d7d0e5; border-radius: .35rem; background: white; color: #52606d; }}
.picker-dropdown {{ position: absolute; z-index: 2; top: calc(100% + .35rem); left: 0; width: 18rem; padding: .75rem; background: white; border: 1px solid #d7d0e5; border-radius: .5rem; box-shadow: 0 8px 24px #32145f22; }}
.picker-header, .picker-actions {{ display: flex; align-items: center; justify-content: space-between; gap: .4rem; }} .picker-arrow {{ color: #5b2aa0; font-size: 1.2rem; text-decoration: none; padding: .1rem .35rem; }}
.picker-weekdays, .picker-days {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: .2rem; }} .picker-weekdays {{ margin: .65rem 0 .25rem; color: #667085; font-size: .7rem; text-align: center; }}
.picker-day {{ padding: .35rem 0; border: 0; background: transparent; color: #182230; border-radius: 50%; cursor: pointer; }} .picker-day:hover, .picker-day.selected {{ background: #5b2aa0; color: white; }} .picker-day.other-month {{ color: #a7a0b4; }}
select, input {{ padding: .45rem; border: 1px solid #d7d0e5; border-radius: .35rem; }} button, .button {{ border: 0; border-radius: .35rem; padding: .5rem .75rem; background: #5b2aa0; color: white; text-decoration: none; cursor: pointer; }}
.views {{ margin-left: auto; display: flex; gap: .35rem; }} .views a.active {{ background: #32145f; }} .week {{ display: grid; grid-template-columns: repeat(7, minmax(8rem, 1fr)); gap: .5rem; overflow-x: auto; }}
.day {{ min-height: 18rem; border: 1px solid #e4e0ee; border-radius: .5rem; background: #fbfaff; padding: .6rem; }} .day h3 {{ margin: 0 0 .6rem; font-size: .85rem; color: #52606d; }}
.appointment-card {{ background: #e5f6ec; border-left: 3px solid #2f9e63; border-radius: .35rem; padding: .55rem; margin-bottom: .45rem; font-size: .82rem; line-height: 1.45; }}
.appointment-card strong {{ color: #17633c; }} .appointment-list {{ display: grid; gap: .5rem; }} .month {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: .35rem; }}
.month-day {{ min-height: 7rem; border: 1px solid #e4e0ee; padding: .45rem; }} .schedule h2 {{ margin-top: 0; }} .schedule form {{ display: flex; flex-wrap: wrap; gap: .7rem; align-items: end; }}
@media (max-width: 850px) {{ .app {{ display: block; }} .sidebar {{ width: 100%; padding: 1rem; }} .nav {{ grid-template-columns: repeat(5, minmax(0, 1fr)); }} .nav a {{ font-size: .75rem; text-align: center; padding: .55rem .2rem; }} .main {{ padding: 1.2rem; }} .views {{ margin-left: 0; }} }}
</style></head><body><div class="app"><aside class="sidebar"><p class="brand">Service Center</p>
<nav class="nav" aria-label="Main navigation">{_nav("/appointments")}</nav></aside><main class="main">
<div class="page-heading"><h1>Appointments</h1><a class="button" href="{escape(service_center_href)}">Schedule Appointment</a></div>
<p class="muted">Schedule and review service visits for existing customers.</p>
<form class="toolbar" method="get"><label>Dealership<select name="dealership"><option value="">All</option>{_options(DEALERSHIPS, dealership)}</select></label>
<label>Agent<select name="agent"><option value="">All</option>{_options(BDC_AGENTS, agent)}</select></label>{picker}
<button>Filter</button><a class="button" href="/appointments">Today</a>
<span class="views"><a class="button {"active" if view == "week" else ""}" href="/appointments?view=week&date={monday.isoformat()}">Week</a>
<a class="button {"active" if view == "month" else ""}" href="/appointments?view=month&date={monday.isoformat()}">Month</a>
<a class="button {"active" if view == "list" else ""}" href="/appointments?view=list&date={monday.isoformat()}">List</a></span></form>
<div class="toolbar"><a class="button" href="/appointments?view={view}&date={(monday - timedelta(days=7)).isoformat()}">Previous</a>
<strong>{monday.isoformat()} - {(monday + timedelta(days=6)).isoformat()}</strong>
<a class="button" href="/appointments?view={view}&date={(monday + timedelta(days=7)).isoformat()}">Next</a></div>
<section class="schedule">{calendar}</section>
</main></div></body></html>"""


def _date_picker_markup(selected_date, picker_month, view, dealership, agent) -> str:
    """Render a dependency-free monthly date picker inside the filter toolbar."""
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(
        picker_month.year, picker_month.month
    )
    weekdays = "".join(
        f'<span>{name}</span>' for name in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    )
    day_buttons = "".join(
        '<div class="picker-week">'
        + "".join(
            f'<button type="button" class="picker-day'
            f'{" selected" if day == selected_date else ""}'
            f'{" other-month" if day.month != picker_month.month else ""}"'
            f'data-date="{day.isoformat()}">{day.day}</button>'
            for day in week
        )
        + "</div>"
        for week in weeks
    )
    return f"""<details class="date-picker"><summary>{selected_date.strftime("%b %d, %Y")}</summary>
<div class="picker-dropdown"><div class="picker-header">
<button type="button" class="picker-arrow picker-prev" aria-label="Previous month">&lsaquo;</button>
<strong class="picker-month-title">{calendar.month_name[picker_month.month]} {picker_month.year}</strong>
<button type="button" class="picker-arrow picker-next" aria-label="Next month">&rsaquo;</button></div>
<div class="picker-weekdays">{weekdays}</div><div class="picker-days">{day_buttons}</div>
<input type="hidden" name="date" value="{selected_date.isoformat()}" data-picker-month="{picker_month.isoformat()}">
<div class="picker-actions"><button type="button" class="picker-clear">Clear</button>
<button type="submit">Apply</button></div></div>
<script>
document.querySelectorAll(".date-picker").forEach(function(picker) {{
  const input = picker.querySelector('input[name="date"]');
  const summary = picker.querySelector("summary");
  const title = picker.querySelector(".picker-month-title");
  const days = picker.querySelector(".picker-days");
  let pickerMonth = new Date(input.dataset.pickerMonth + "T00:00:00");
  function bindDays() {{
    picker.querySelectorAll(".picker-day").forEach(function(day) {{
    day.addEventListener("click", function() {{
      input.value = day.dataset.date;
      summary.textContent = new Date(day.dataset.date + "T00:00:00").toLocaleDateString(undefined, {{month: "short", day: "2-digit", year: "numeric"}});
      picker.querySelectorAll(".picker-day").forEach(function(item) {{ item.classList.remove("selected"); }});
      day.classList.add("selected");
    }});
    }});
  }}
  function renderMonth(month) {{
    pickerMonth = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth(), 1));
    const firstOffset = (pickerMonth.getUTCDay() + 6) % 7;
    let markup = "";
    for (let index = 0; index < 42; index += 1) {{
      const day = new Date(Date.UTC(pickerMonth.getUTCFullYear(), pickerMonth.getUTCMonth(), index - firstOffset + 1));
      const iso = day.toISOString().slice(0, 10);
      const selected = iso === input.value ? " selected" : "";
      const other = day.getUTCMonth() === pickerMonth.getUTCMonth() ? "" : " other-month";
      markup += '<button type="button" class="picker-day' + selected + other + '" data-date="' + iso + '">' + day.getUTCDate() + "</button>";
    }}
    days.innerHTML = markup;
    title.textContent = pickerMonth.toLocaleDateString(undefined, {{month: "long", year: "numeric", timeZone: "UTC"}});
    bindDays();
  }}
  picker.querySelector(".picker-prev").addEventListener("click", function() {{
    renderMonth(new Date(Date.UTC(pickerMonth.getUTCFullYear(), pickerMonth.getUTCMonth() - 1, 1)));
  }});
  picker.querySelector(".picker-next").addEventListener("click", function() {{
    renderMonth(new Date(Date.UTC(pickerMonth.getUTCFullYear(), pickerMonth.getUTCMonth() + 1, 1)));
  }});
  bindDays();
  picker.querySelector(".picker-clear").addEventListener("click", function() {{
    input.value = "";
    summary.textContent = "Select date";
    picker.querySelectorAll(".picker-day").forEach(function(item) {{ item.classList.remove("selected"); }});
  }});
}});
</script></details>"""


def _appointment_card(appointment) -> str:
    """Render only the required appointment card fields."""
    customer_query = urlencode(
        {
            "dealership": appointment.dealership,
            "agent": appointment.assigned_agent,
            "customer": appointment.customer_name,
        }
    )
    return (
        f'<article class="appointment-card"><strong><a href="/service-center?{escape(customer_query)}">'
        f'{escape(appointment.customer_name)}</a></strong><br>'
        f'VIN: {escape(appointment.vin)}<br>{appointment.scheduled_date.isoformat()} '
        f'{appointment.scheduled_time.strftime("%H:%M")}<br>'
        f'<small>{escape(appointment.status.title())}'
        + (f' · {escape(appointment.service_type)}' if appointment.service_type else '')
        + (f' · {appointment.mileage:,} mi' if appointment.mileage is not None else '')
        + (f'<br>{escape(appointment.reason)}' if appointment.reason else '')
        + '</small></article>'
    )


def _appointment_week(appointments, days) -> str:
    """Render appointments in seven day columns."""
    return '<div class="week">' + "".join(
        f'<div class="day"><h3>{day.strftime("%a %b %d")}</h3>'
        + "".join(_appointment_card(item) for item in appointments if item.scheduled_date == day)
        + "</div>"
        for day in days
    ) + "</div>"


def _appointment_month(appointments, anchor) -> str:
    """Render a compact month-style appointment grid."""
    start = anchor.replace(day=1)
    days = tuple(start + timedelta(days=index) for index in range(35))
    return '<div class="month">' + "".join(
        f'<div class="month-day"><strong>{day.day}</strong>'
        + "".join(_appointment_card(item) for item in appointments if item.scheduled_date == day)
        + "</div>"
        for day in days
    ) + "</div>"


def _service_center_page(
    state: DashboardState,
    rows,
    dealership,
    agent,
    language,
    selected,
) -> str:
    """Render the selected-customer Service Center workspace."""
    row = next(
        (candidate for candidate in rows if candidate.customer.customer_name == selected),
        None,
    )
    fields = _filter_fields(dealership, agent, language)
    customer_options = "".join(
        f'<option value="{escape(candidate.customer.customer_name)}"'
        f'{" selected" if candidate.customer.customer_name == selected else ""}>'
        f'{escape(candidate.customer.customer_name)}</option>'
        for candidate in rows
    )
    if row is None:
        return _service_center_empty_page()
    customer = row.customer
    draft = row.draft
    body = "" if customer.customer_name in state.composer_cleared else (draft.body if draft else "")
    service_type_options = _service_type_options()
    draft_language = draft.language_preference if draft else customer.language_preference
    outbox_status = row.outbox.status.value if row.outbox else "not queued"
    history_html = "".join(
        (
            f'<div class="msg in"><div class="msg-head"><strong>{escape(entry.sender)}</strong>'
            f'<span>{entry.timestamp:%m/%d/%Y, %I:%M %p}</span></div>'
            f'<div class="msg-body">{escape(entry.body)}</div>'
            f'<div class="msg-tag">Simulated customer reply &middot; demo only, not a real text</div></div>'
            if entry.direction == "incoming"
            else f'<div class="msg out"><div class="msg-head"><strong>You ({escape(entry.sender)})</strong>'
            f'<span>{entry.timestamp:%m/%d/%Y, %I:%M %p}</span></div>'
            f'<div class="msg-body">{escape(entry.body)}</div>'
            f'<div class="msg-tag">{escape(entry.event)} &middot; simulated, not a delivered SMS</div></div>'
        )
        for entry in state.message_history(customer.customer_name)
    ) or '<p class="muted">No message history yet.</p>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width, initial-scale=1"><title>Service Center</title>
<style>
* {{ box-sizing: border-box; }} body {{ margin: 0; font-family: system-ui, sans-serif;
background: #f6f5fb; color: #182230; }} .app {{ display: flex; min-height: 100vh; }}
.sidebar {{ width: 230px; flex: 0 0 230px; padding: 1.5rem 1rem; background: #32145f; color: white; }}
.brand {{ font-size: 1.2rem; font-weight: 700; margin: 0 0 2rem; }} .nav {{ display: grid; gap: .35rem; }}
.nav a {{ color: #e8ddff; padding: .7rem .8rem; border-radius: .45rem; text-decoration: none; }}
.nav-icon {{ width: 1rem; height: 1rem; margin-right: .55rem; vertical-align: -0.15rem; fill: none;
stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }}
.nav a.active, .nav a:hover {{ background: #5b2aa0; color: white; }} .main {{ width: 100%; padding: 2rem 2.5rem; }}
h1 {{ margin: 0; color: #281047; }} .muted {{ color: #667085; }} .filters, .panel, .customer-card, .service-card {{
background: white; border: 1px solid #ebe7f4; border-radius: .7rem; box-shadow: 0 3px 12px #32145f12;
padding: 1rem; margin-bottom: 1rem; }} .filters {{ display: flex; flex-wrap: wrap; align-items: end; gap: .7rem; }}
label {{ display: grid; gap: .25rem; color: #52606d; font-size: .85rem; }} select, input, textarea {{
padding: .45rem; border: 1px solid #d7d0e5; border-radius: .35rem; }} button {{ margin: .15rem; padding: .45rem .7rem;
cursor: pointer; border: 0; border-radius: .35rem; background: #5b2aa0; color: white; }} .layout {{
display: grid; grid-template-columns: minmax(15rem, .8fr) minmax(20rem, 1.2fr); gap: 1rem; }}
.customer-card h2, .panel h2, .service-card h2 {{ margin-top: 0; }} .customer-card strong {{ color: #32145f; }}
.details {{ line-height: 1.7; }} .message-panel textarea {{ width: 100%; min-height: 10rem; resize: vertical; }}
.message-actions {{ display: flex; justify-content: flex-end; gap: .35rem; margin-top: .5rem; }}
.message-columns {{ display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 1rem; }}
.history {{ max-height: 22rem; overflow-y: auto; border-left: 1px solid #ebe7f4; padding-left: 1rem; }}
.history h3 {{ margin: 0 0 .5rem; font-size: 1rem; color: #32145f; }}
.msg {{ margin-bottom: .7rem; }} .msg-head {{ display: flex; justify-content: space-between; gap: .5rem;
font-size: .8rem; color: #52606d; }} .msg-body {{ margin-top: .2rem; padding: .5rem .7rem; border-radius: .5rem;
background: #e9e4fb; overflow-wrap: anywhere; }} .msg-tag {{ margin-top: .15rem; font-size: .72rem; color: #667085; }}
.msg.in .msg-body {{ background: #f0f1f4; }} .reply-form {{ margin-top: .8rem; display: grid; gap: .3rem; }}
.service-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .7rem; }}
.service-grid .wide {{ grid-column: 1 / -1; }} @media (max-width: 850px) {{
.app {{ display: block; }} .sidebar {{ width: 100%; padding: 1rem; }} .brand {{ margin-bottom: .8rem; }}
.nav {{ grid-template-columns: repeat(5, minmax(0, 1fr)); }} .nav a {{ font-size: .75rem; text-align: center; padding: .55rem .2rem; }}
.main {{ padding: 1.2rem; }} .layout {{ grid-template-columns: 1fr; }} .message-columns {{ grid-template-columns: 1fr; }}
.history {{ border-left: 0; padding-left: 0; }} }}
</style></head><body><div class="app"><aside class="sidebar"><p class="brand">Service Center</p>
<nav class="nav" aria-label="Main navigation">{_nav("/service-center")}</nav></aside>
<main class="main"><h1>Service Center</h1><p class="muted">Review customer details, prepare a bilingual reminder,
and record completed service.</p>
<form class="filters" method="get" action="/service-center"><label>Dealership
<select name="dealership"><option value="">All</option>{_options(DEALERSHIPS, dealership)}</select></label>
<label>Agent <select name="agent"><option value="">All</option>{_options(BDC_AGENTS, agent)}</select></label>
<label>Language <select name="language"><option value="">All</option>{_options(CustomerLanguage, language)}</select></label>
<label>Customer <select name="customer"><option value="">Select customer</option>{customer_options}</select></label>
<button>Filter</button> <a href="/service-center">Reset</a></form>
<div class="layout"><section class="customer-card"><h2>Selected Customer</h2><div class="details">
<strong>{escape(customer.customer_name)}</strong><br>{escape(customer.email)}<br>{escape(customer.phone)}<br>
{customer.vehicle.year} {escape(customer.vehicle.make)} {escape(customer.vehicle.model)}<br>
VIN: {escape(customer.vehicle.vin)}<br>Dealership: {escape(customer.dealership)}<br>
Assigned BDC Agent: {escape(customer.bdc_agent)}<br>Expected service date: {row.expected_date.isoformat()}<br>
Reminder status: {escape(draft.status if draft else "none")}<br>Outbox: {escape(outbox_status)}</div></section>
<section class="panel message-panel"><h2>Messages</h2><div class="message-columns"><form method="post">
<input type="hidden" name="return_to" value="service-center"><input type="hidden" name="customer_name"
value="{escape(customer.customer_name)}">{fields}<input type="hidden" name="message_language"
value="{escape(draft_language.value)}"><label>Message<textarea name="message_body"
required>{escape(body)}</textarea></label><div class="message-actions">
<button name="action" value="save_draft">Save as Draft</button>
<button name="action" value="send_message">Send Message</button></div></form>
<aside class="history" aria-label="Message History"><h3>Message History</h3>{history_html}
<form method="post" class="reply-form"><input type="hidden" name="return_to" value="service-center">
<input type="hidden" name="customer_name" value="{escape(customer.customer_name)}">{fields}
<label>Simulated customer reply (demo)<input name="reply_body" required></label>
<button name="action" value="simulate_reply">Add Demo Reply</button></form></aside></div></section></div>
<script>(function(){{var h=document.querySelector(".history");if(h){{h.scrollTop=h.scrollHeight;}}}})();</script>
<section class="service-card"><h2>Record Service</h2><form method="post">
<input type="hidden" name="return_to" value="service-center"><input type="hidden" name="customer_name"
value="{escape(customer.customer_name)}">{fields}<div class="service-grid"><label>Service Date
<input type="date" name="service_date" required></label><label>Mileage
<input type="number" name="mileage" min="0" step="1" value="{customer.vehicle.current_mileage}" required></label><label>Service Type
<select name="service_type" required>{service_type_options}</select></label>
<label>Technician<input name="technician" value="{escape(customer.bdc_agent)}"></label>
<label class="wide">Reason for Visit<input name="reason"></label>
<label class="wide">Notes<textarea name="notes"></textarea></label>
</div><button name="action" value="service">Record Service</button></form></section>
<section class="service-card"><h2>Schedule Appointment</h2><form method="post">
<input type="hidden" name="return_to" value="service-center"><input type="hidden" name="customer_name"
value="{escape(customer.customer_name)}">{fields}<div class="service-grid"><label>Appointment Date
<input type="date" name="appointment_date" required></label><label>Appointment Time
<input type="time" name="appointment_time" required></label><label>Mileage
<input type="number" name="mileage" min="0" step="1" value="{customer.vehicle.current_mileage}"></label>
<label>Service Type<select name="service_type" required>{service_type_options}</select></label>
<label class="wide">Reason for Visit<input name="reason"></label>
</div><button name="action" value="schedule_appointment">Schedule Appointment</button></form></section>
</main></div></body></html>"""


def _service_center_empty_page() -> str:
    """Render an empty filtered Service Center result."""
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Service Center</title></head><body><h1>Service Center</h1>
<p>No customers match the selected filters.</p><a href="/service-center">Reset</a></body></html>"""


def _options(values, selected) -> str:
    """Render select options for strings or enums."""
    return "".join(
        f'<option value="{escape(value.value if hasattr(value, "value") else value)}"'
        f'{" selected" if value == selected or getattr(value, "value", None) == selected else ""}>'
        f'{escape(value.value if hasattr(value, "value") else value)}</option>'
        for value in values
    )


def _row(row, fields: str = "") -> str:
    """Render one customer data row without workflow controls."""
    customer = row.customer
    return (
        f"<tr><td><strong>{escape(customer.customer_name)}</strong><br>"
        f"{escape(customer.email)}<small>{escape(customer.phone)}<br>"
        f"{customer.vehicle.year} "
        f"{escape(customer.vehicle.make)} {escape(customer.vehicle.model)}<br>"
        f"VIN: {escape(customer.vehicle.vin)}</small></td><td>{escape(customer.dealership)}<br>"
        f"Agent: {escape(customer.bdc_agent)}</td></tr>"
    )


def _action(customer_name: str, action: str, label: str, fields: str = "") -> str:
    """Render a one-click POST action that keeps the active filters."""
    return (
        f'<form method="post" style="display:inline"><input type="hidden" '
        f'name="customer_name" value="{escape(customer_name)}">'
        f'<input type="hidden" name="action" value="{action}">{fields}'
        f"<button>{label}</button></form>"
    )


def _service_type_options() -> str:
    """Render the only service types accepted for new submissions."""
    return "".join(f"<option>{escape(name)}</option>" for name in SERVICE_TYPES)


def _service_form(customer_name: str, fields: str) -> str:
    """Render the completed-service form for one customer."""
    return (
        f'<form method="post" class="service-form"><input type="hidden" name="customer_name" '
        f'value="{escape(customer_name)}"><input type="hidden" name="action" '
        f'value="service">{fields}<div class="service-row"><label>Service date'
        f'<input type="date" name="service_date" required></label><label>Mileage'
        f'<input type="number" name="mileage" min="0" placeholder="Mileage" '
        f'required></label></div><div class="service-row"><label>Service type'
        f'<select name="service_type" required>{_service_type_options()}</select></label>'
        f'<label>Notes<input name="notes" placeholder="Notes"></label></div>'
        f'<button>Record service</button></form>'
    )


if __name__ == "__main__":
    run_dashboard()
