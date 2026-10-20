"""In-memory orchestration for the local reminder demonstration dashboard."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, time
import shutil

from app.data.seed_customers import FICTIONAL_CUSTOMERS
from app.models.customer import Customer, CustomerLanguage
from app.models.appointment import Appointment
from app.models.holiday import HolidayCalendar, HolidayClosure
from app.models.message import (
    MessageChannel,
    MessageDraft,
    MessageLogEntry,
    MessageStatus,
)
from app.models.outbox import OutboxMessage, OutboxStatus
from app.models.service_history import ServiceHistoryEntry
from app.services.customer_service import expected_service_date, is_customer_due
from app.services.message_outbox import (
    mark_simulated_sent,
    queue_approved_message,
)
from app.services.message_review import approve_draft, reject_draft
from app.services.message_routing import route_message_drafts
from app.services.messaging import generate_service_reminder, generate_upcoming_reminder
from app.services.database import Database
from app.services.service_history_store import ServiceHistoryStore


@dataclass(frozen=True)
class DashboardRow:
    """Read-only customer and workflow data rendered by the dashboard."""

    customer: Customer
    expected_date: date
    due: bool
    draft: MessageDraft | None
    deferred_to: date | None
    closure_name: str | None
    outbox: OutboxMessage | None


def _validate_mileage(value: object) -> int:
    """Accept only nonnegative whole numbers."""
    if isinstance(value, bool):
        raise ValueError("Mileage must be a whole number")
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value.isdigit():
            raise ValueError("Mileage must be a nonnegative whole number")
        return int(value)
    if not isinstance(value, int) or value < 0:
        raise ValueError("Mileage must be a nonnegative whole number")
    return value


def demo_holiday_calendars() -> dict[str, HolidayCalendar]:
    """Return a small visible demo configuration without changing seed data."""
    return {
        "Chevrolet": HolidayCalendar(
            "Chevrolet",
            (HolidayClosure(date(2025, 4, 15), "Spring inventory closure"),),
        ),
        "Kia": HolidayCalendar(
            "Kia",
            (HolidayClosure(date(2025, 4, 15), "Kia service holiday"),),
        ),
    }


class DashboardState:
    """Coordinate the in-memory customer-to-outbox demonstration workflow."""

    def __init__(
        self,
        customers: Iterable[Customer] = FICTIONAL_CUSTOMERS,
        current_date: date = date(2027, 1, 1),
        holiday_calendars: Mapping[str, HolidayCalendar] | None = None,
        history_store: ServiceHistoryStore | None = None,
        database: Database | None = None,
    ) -> None:
        self.database = database
        self.history_store = history_store
        customers = tuple(customers)
        if database:
            database.seed_customers(customers)
            self._import_legacy_history(customers)
        self.customers = self._restore_history(customers)
        self.current_date = current_date
        self.holiday_calendars = dict(holiday_calendars or {})
        self._validate_calendars()
        generated = (
            generate_service_reminder(
                customer,
                current_date,
                holiday_calendar=self.holiday_calendars.get(customer.dealership),
            )
            for customer in self.customers
        )
        self._drafts = {
            draft.customer_name: draft
            for draft in route_message_drafts(self.customers, generated)
        }
        for customer in self.customers:
            if customer.service_history and customer.customer_name not in self._drafts:
                self._drafts.update({
                    draft.customer_name: draft
                    for draft in route_message_drafts(
                        (customer,), (generate_upcoming_reminder(customer),)
                    )
                })
        self._outbox: tuple[OutboxMessage, ...] = ()
        self._message_log: tuple[MessageLogEntry, ...] = ()
        self.composer_cleared: set[str] = set()
        self._appointments = self._load_appointments()

    @property
    def outbox(self) -> tuple[OutboxMessage, ...]:
        """Return the immutable simulated outbox snapshot."""
        return self._outbox

    @property
    def appointments(self) -> tuple[Appointment, ...]:
        """Return scheduled appointments in chronological order."""
        return tuple(
            sorted(
                self._appointments,
                key=lambda appointment: (
                    appointment.scheduled_date,
                    appointment.scheduled_time,
                ),
            )
        )

    def schedule_appointment(
        self,
        customer_name: str,
        scheduled_date: date,
        scheduled_time,
        service_type: str | None = None,
        reason: str | None = None,
        mileage: int | None = None,
    ) -> Appointment:
        """Schedule an existing customer for a validated date and time."""
        if scheduled_date is None or scheduled_time is None:
            raise ValueError("Appointment date and time are required")
        customer = self.customers[self._customer_index(customer_name)]
        if mileage is None:
            mileage = customer.vehicle.current_mileage
        mileage = _validate_mileage(mileage)
        appointment = Appointment(
            customer_name=customer.customer_name,
            vin=customer.vehicle.vin,
            dealership=customer.dealership,
            assigned_agent=customer.bdc_agent,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            service_type=service_type or None,
            reason=(reason or "").strip() or None,
            mileage=mileage,
        )
        self._appointments = tuple(
            existing
            for existing in self._appointments
            if not (
                existing.vin == customer.vehicle.vin
                and existing.scheduled_date == scheduled_date
                and existing.scheduled_time == scheduled_time
            )
        ) + (appointment,)
        if self.database:
            self.database.save_appointment(
                customer.vehicle.vin, customer.dealership, customer.bdc_agent,
                scheduled_date, scheduled_time, service_type=appointment.service_type,
                reason=appointment.reason, mileage=mileage,
            )
        return appointment

    def rows(
        self,
        dealership: str | None = None,
        assigned_agent: str | None = None,
        language: CustomerLanguage | None = None,
    ) -> tuple[DashboardRow, ...]:
        """Return filtered customer workflow rows."""
        return tuple(
            self._row_for(customer)
            for customer in self.customers
            if (dealership is None or customer.dealership == dealership)
            and (assigned_agent is None or customer.bdc_agent == assigned_agent)
            and (language is None or customer.language_preference is language)
        )

    def approve(self, customer_name: str) -> MessageDraft:
        """Approve a routed draft for one customer."""
        draft = self._require_draft(customer_name)
        approved = approve_draft(draft)
        self._drafts[customer_name] = approved
        return approved

    def reject(self, customer_name: str, reason: str) -> MessageDraft:
        """Reject a routed draft for one customer with a required reason."""
        draft = self._require_draft(customer_name)
        rejected = reject_draft(draft, reason)
        self._drafts[customer_name] = rejected
        return rejected

    def message_history(self, customer_name: str) -> tuple[MessageLogEntry, ...]:
        """Return one customer's recorded message events, oldest first."""
        if self.database:
            customer = self.customers[self._customer_index(customer_name)]
            return tuple(
                MessageLogEntry(
                    customer_name,
                    row["sender"],
                    row["body"],
                    row["event"],
                    datetime.fromisoformat(row["created_at"]),
                    row["direction"],
                    bool(row["simulated"]),
                )
                for row in self.database.message_rows(customer.vehicle.vin)
            )
        return tuple(
            entry for entry in self._message_log if entry.customer_name == customer_name
        )

    def simulate_reply(self, customer_name: str, body: str) -> MessageLogEntry:
        """Record a clearly simulated incoming customer reply for the demo."""
        if not body.strip():
            raise ValueError("Reply text is required")
        customer = self.customers[self._customer_index(customer_name)]
        return self._append_log(customer, customer.customer_name, body.strip(), "Demo reply", "incoming")

    def _log_message(self, draft: MessageDraft, event: str) -> None:
        customer = self.customers[self._customer_index(draft.customer_name)]
        self._append_log(customer, draft.assigned_agent or "Agent", draft.body, event, "outgoing")

    def _append_log(
        self, customer: Customer, sender: str, body: str, event: str, direction: str
    ) -> MessageLogEntry:
        entry = MessageLogEntry(
            customer.customer_name, sender, body, event, datetime.now(), direction
        )
        if self.database:
            self.database.save_message(
                customer.vehicle.vin, customer.dealership, direction, sender, body, event
            )
        else:
            self._message_log = (*self._message_log, entry)
        return entry

    def save_draft(
        self,
        customer_name: str,
        body: str,
        language: CustomerLanguage,
    ) -> MessageDraft:
        """Save editable Service Center copy as an unapproved draft."""
        draft = self._store_draft(customer_name, body, language)
        self.composer_cleared.discard(customer_name)
        self._log_message(draft, "Draft saved")
        return draft

    def _store_draft(
        self,
        customer_name: str,
        body: str,
        language: CustomerLanguage,
    ) -> MessageDraft:
        customer = self.customers[self._customer_index(customer_name)]
        draft = MessageDraft(
            customer_name=customer.customer_name,
            contact=customer.email,
            channel=MessageChannel.EMAIL,
            body=body,
            status=MessageStatus.DRAFT.value,
            assigned_agent=customer.bdc_agent,
            dealership=customer.dealership,
            language_preference=language,
        )
        self._drafts[customer_name] = draft
        return draft

    def send_message(
        self,
        customer_name: str,
        body: str,
        language: CustomerLanguage,
    ) -> OutboxMessage:
        """Approve and simulate-send one conversation message.

        Conversation messages are not automated reminders, so they bypass the
        duplicate-reminder check in ``queue``; each send is its own outbox entry.
        """
        original = self._drafts.get(customer_name)
        self._store_draft(customer_name, body, language)
        self._drafts[customer_name] = replace(
            self._drafts[customer_name],
            status=MessageStatus.REVIEW_READY.value,
        )
        approved = self.approve(customer_name)
        if not approved.assigned_agent or not approved.dealership:
            raise ValueError("Only routed messages can be queued")
        self._outbox = (*self._outbox, OutboxMessage(draft=approved))
        sent = self.simulate_send(customer_name)
        # Keep any default reminder or saved draft; only the composer is cleared.
        if original is None:
            self._drafts.pop(customer_name, None)
        else:
            self._drafts[customer_name] = original
        self.composer_cleared.add(customer_name)
        return sent

    def queue(self, customer_name: str) -> OutboxMessage:
        """Queue an approved customer draft in the simulated outbox."""
        draft = self._require_draft(customer_name)
        message = queue_approved_message(draft, self._outbox)
        self._outbox = (*self._outbox, message)
        return message

    def simulate_send(self, customer_name: str) -> OutboxMessage:
        """Mark a queued customer message as simulated sent."""
        index = self._outbox_index(customer_name)
        sent = mark_simulated_sent(self._outbox[index])
        self._outbox = (
            *self._outbox[:index],
            sent,
            *self._outbox[index + 1 :],
        )
        self._log_message(sent.draft, "Simulated send")
        return sent

    def record_service_visit(
        self,
        customer_name: str,
        service_date: date,
        mileage: int,
        service_type: str,
        notes: str | None = None,
        description: str | None = None,
        technician: str | None = None,
        reason: str | None = None,
    ) -> Customer:
        """Record service and rebuild only that customer's future workflow."""
        mileage = _validate_mileage(mileage)
        index = self._customer_index(customer_name)
        customer = self.customers[index]
        entry = ServiceHistoryEntry(
            service_date,
            mileage,
            service_type,
            notes,
            description,
            technician or customer.bdc_agent,
            reason,
        )
        history = (*customer.service_history, entry)
        updated = replace(
            customer,
            last_service_date=max(customer.last_service_date, service_date),
            vehicle=replace(
                customer.vehicle,
                current_mileage=max(customer.vehicle.current_mileage, mileage),
            ),
            service_history=history,
        )
        self.customers = (*self.customers[:index], updated, *self.customers[index + 1 :])
        if self.database:
            self.database.save_visit(updated.vehicle.vin, updated.dealership, entry)
            self._appointments = self._appointments_from_database()
        else:
            self._complete_matching_appointment(updated.vehicle.vin, service_date)
            if self.history_store:
                self.history_store.save(updated.vehicle.vin, updated.service_history)
        self._drafts.pop(customer_name, None)
        self.composer_cleared.discard(customer_name)
        self._outbox = tuple(
            message
            for message in self._outbox
            if message.draft.customer_name != customer_name
        )
        generated = generate_service_reminder(
            updated,
            self.current_date,
            holiday_calendar=self.holiday_calendars.get(updated.dealership),
        )
        routed = route_message_drafts(
            (updated,), (generated or generate_upcoming_reminder(updated),)
        )
        if routed:
            self._drafts[customer_name] = routed[0]
        return updated

    def service_history(self) -> tuple[tuple[Customer, ServiceHistoryEntry], ...]:
        """Return completed visits newest first across the current customers."""
        visits = [
            (customer, entry)
            for customer in self.customers
            for entry in customer.service_history
        ]
        return tuple(
            sorted(
                visits,
                key=lambda visit: (visit[1].service_date, visit[0].customer_name),
                reverse=True,
            )
        )

    def _import_legacy_history(self, customers: tuple[Customer, ...]) -> None:
        """Copy any old JSON history into the database once, keeping the JSON file."""
        store = self.history_store
        if not store or self.database.get_meta("legacy_json_imported"):
            return
        if store.path.exists():
            self.database.backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(store.path, self.database.backup_dir / f"service_history-{stamp}.json")
            existing = self.database.visits_by_vin()
            by_vin = {customer.vehicle.vin: customer for customer in customers}
            for vin, entries in store.load().items():
                customer = by_vin.get(vin)
                if customer is None:
                    continue
                known = existing.get(vin, ())
                for entry in entries:
                    if entry not in known:
                        self.database.save_visit(vin, customer.dealership, entry)
        self.database.set_meta("legacy_json_imported", datetime.now().isoformat(timespec="seconds"))

    def _restore_history(self, customers: tuple[Customer, ...]) -> tuple[Customer, ...]:
        """Load persisted records onto matching seed customer/vehicle identities."""
        if self.database:
            persisted = self.database.visits_by_vin()
            saved_mileage = self.database.current_mileage_by_vin()
        elif self.history_store:
            persisted = self.history_store.load()
            saved_mileage = {}
        else:
            return customers
        restored = []
        for customer in customers:
            history = persisted.get(customer.vehicle.vin, ())
            vin_saved = saved_mileage.get(customer.vehicle.vin)
            if not history and vin_saved is None:
                restored.append(customer)
                continue
            latest_date = max((entry.service_date for entry in history), default=customer.last_service_date)
            known = [customer.vehicle.current_mileage if vin_saved is None else vin_saved]
            known.extend(entry.mileage for entry in history)
            restored.append(
                replace(
                    customer,
                    last_service_date=max(customer.last_service_date, latest_date),
                    vehicle=replace(customer.vehicle, current_mileage=max(known)),
                    service_history=history or customer.service_history,
                )
            )
        return tuple(restored)

    def _row_for(self, customer: Customer) -> DashboardRow:
        """Build one read-only presentation row from domain state."""
        expected_date = expected_service_date(customer)
        calendar = self.holiday_calendars.get(customer.dealership)
        closure = calendar.closure_for(expected_date) if calendar else None
        deferred_to = calendar.next_open_date(expected_date) if closure else None
        return DashboardRow(
            customer=customer,
            expected_date=expected_date,
            due=is_customer_due(customer, self.current_date),
            draft=self._drafts.get(customer.customer_name),
            deferred_to=deferred_to,
            closure_name=closure.name if closure else None,
            outbox=next(
                (
                    message
                    for message in reversed(self._outbox)
                    if message.draft.customer_name == customer.customer_name
                ),
                None,
            ),
        )

    def _require_draft(self, customer_name: str) -> MessageDraft:
        """Return a workflow draft or explain why one is unavailable."""
        try:
            return self._drafts[customer_name]
        except KeyError as error:
            raise ValueError("Customer is not due and has no draft") from error

    def _customer_index(self, customer_name: str) -> int:
        """Find a customer by name or explain why it is unavailable."""
        for index, customer in enumerate(self.customers):
            if customer.customer_name == customer_name:
                return index
        raise ValueError(f"Customer not found: {customer_name}")

    def _outbox_index(self, customer_name: str) -> int:
        """Find a customer's newest queued outbox record, else their newest one."""
        indexes = [
            index
            for index, message in enumerate(self._outbox)
            if message.draft.customer_name == customer_name
        ]
        if not indexes:
            raise ValueError("Customer has no queued outbox message")
        queued = [i for i in indexes if self._outbox[i].status == OutboxStatus.QUEUED]
        return (queued or indexes)[-1]

    def _validate_calendars(self) -> None:
        """Reject mappings whose keys disagree with calendar ownership."""
        for dealership, calendar in self.holiday_calendars.items():
            if dealership != calendar.dealership:
                raise ValueError("Holiday calendar mapping does not match dealership")

    def _load_appointments(self) -> tuple[Appointment, ...]:
        """Load saved appointments, seeding the labelled demo ones only once."""
        if not self.database:
            return self._demo_appointments()
        if not self.database.get_meta("demo_appointments_seeded"):
            for demo in self._demo_appointments():
                self.database.save_appointment(
                    demo.vin, demo.dealership, demo.assigned_agent,
                    demo.scheduled_date, demo.scheduled_time, is_demo=True,
                )
            self.database.set_meta("demo_appointments_seeded", "1")
        return self._appointments_from_database()

    def _appointments_from_database(self) -> tuple[Appointment, ...]:
        return tuple(
            Appointment(
                customer_name=row["name"],
                vin=row["vin"],
                dealership=row["dealership"],
                assigned_agent=row["assigned_agent"],
                scheduled_date=date.fromisoformat(row["scheduled_date"]),
                scheduled_time=datetime.strptime(row["scheduled_time"], "%H:%M").time(),
                is_demo=bool(row["is_demo"]),
                status=row["status"],
                service_type=row["service_type"],
                reason=row["reason"],
                mileage=row["mileage"],
            )
            for row in self.database.appointment_rows()
        )

    def _complete_matching_appointment(self, vin: str, service_date: date) -> None:
        """Mark one open same-day appointment completed (in-memory mode)."""
        updated = []
        done = False
        for appointment in sorted(self._appointments, key=lambda a: a.scheduled_time):
            if (not done and appointment.vin == vin and appointment.status == "scheduled"
                    and appointment.scheduled_date == service_date):
                appointment = replace(appointment, status="completed")
                done = True
            updated.append(appointment)
        self._appointments = tuple(updated)

    def _demo_appointments(self) -> tuple[Appointment, ...]:
        """Create clearly marked demo appointments from existing customers."""
        demo = []
        for offset, customer in enumerate(self.customers[:3]):
            demo.append(
                Appointment(
                    customer_name=customer.customer_name,
                    vin=customer.vehicle.vin,
                    dealership=customer.dealership,
                    assigned_agent=customer.bdc_agent,
                    scheduled_date=date(2027, 1, 4 + offset),
                    scheduled_time=time(9 + offset, 0),
                    is_demo=True,
                )
            )
        return tuple(demo)
