"""In-memory orchestration for the local reminder demonstration dashboard."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, time

from app.data.seed_customers import FICTIONAL_CUSTOMERS
from app.models.customer import Customer, CustomerLanguage
from app.models.appointment import Appointment
from app.models.holiday import HolidayCalendar, HolidayClosure
from app.models.message import MessageChannel, MessageDraft, MessageStatus
from app.models.outbox import OutboxMessage
from app.models.service_history import ServiceHistoryEntry
from app.services.customer_service import expected_service_date, is_customer_due
from app.services.message_outbox import (
    mark_simulated_sent,
    queue_approved_message,
)
from app.services.message_review import approve_draft, reject_draft
from app.services.message_routing import route_message_drafts
from app.services.messaging import generate_service_reminder


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
    ) -> None:
        self.customers = tuple(customers)
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
        self._outbox: tuple[OutboxMessage, ...] = ()
        self._appointments = self._demo_appointments()

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
    ) -> Appointment:
        """Schedule an existing customer for a validated date and time."""
        if scheduled_date is None or scheduled_time is None:
            raise ValueError("Appointment date and time are required")
        customer = self.customers[self._customer_index(customer_name)]
        appointment = Appointment(
            customer_name=customer.customer_name,
            vin=customer.vehicle.vin,
            dealership=customer.dealership,
            assigned_agent=customer.bdc_agent,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
        )
        self._appointments = tuple(
            existing
            for existing in self._appointments
            if not (
                existing.customer_name == customer_name
                and existing.scheduled_date == scheduled_date
                and existing.scheduled_time == scheduled_time
            )
        ) + (appointment,)
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

    def save_draft(
        self,
        customer_name: str,
        body: str,
        language: CustomerLanguage,
    ) -> MessageDraft:
        """Save editable Service Center copy as an unapproved draft."""
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
        """Approve, queue, and simulate-send edited Service Center copy."""
        self.save_draft(customer_name, body, language)
        self._drafts[customer_name] = replace(
            self._drafts[customer_name],
            status=MessageStatus.REVIEW_READY.value,
        )
        self.approve(customer_name)
        self.queue(customer_name)
        return self.simulate_send(customer_name)

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
        return sent

    def record_service_visit(
        self,
        customer_name: str,
        service_date: date,
        mileage: int,
        service_type: str,
        notes: str | None = None,
    ) -> Customer:
        """Record service and rebuild only that customer's future workflow."""
        index = self._customer_index(customer_name)
        customer = self.customers[index]
        entry = ServiceHistoryEntry(service_date, mileage, service_type, notes)
        updated = replace(customer, service_history=(*customer.service_history, entry))
        self.customers = (*self.customers[:index], updated, *self.customers[index + 1 :])
        self._drafts.pop(customer_name, None)
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
        routed = route_message_drafts((updated,), (generated,))
        if routed:
            self._drafts[customer_name] = routed[0]
        return updated

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
                    for message in self._outbox
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
        """Find a customer's simulated outbox record."""
        for index, message in enumerate(self._outbox):
            if message.draft.customer_name == customer_name:
                return index
        raise ValueError("Customer has no queued outbox message")

    def _validate_calendars(self) -> None:
        """Reject mappings whose keys disagree with calendar ownership."""
        for dealership, calendar in self.holiday_calendars.items():
            if dealership != calendar.dealership:
                raise ValueError("Holiday calendar mapping does not match dealership")

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
