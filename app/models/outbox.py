"""Immutable records for the simulated outbound message queue."""

from dataclasses import dataclass
from enum import Enum

from app.models.customer import CustomerLanguage
from app.models.message import MessageDraft, MessageStatus


class OutboxStatus(str, Enum):
    """Delivery states supported by the simulated outbox."""

    QUEUED = "queued"
    SIMULATED_SENT = "simulated_sent"
    FAILED = "failed"


@dataclass(frozen=True)
class OutboxMessage:
    """A queued approved draft with simulated delivery state."""

    draft: MessageDraft
    status: OutboxStatus = OutboxStatus.QUEUED
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.draft.status != MessageStatus.APPROVED.value:
            raise ValueError("Only approved messages can enter the outbox")
        if not isinstance(self.status, OutboxStatus):
            raise ValueError("Outbox status is not recognized")
        if self.status == OutboxStatus.FAILED:
            if self.failure_reason is None or not self.failure_reason.strip():
                raise ValueError("Failed outbox messages require a failure reason")
        elif self.failure_reason is not None:
            raise ValueError("Only failed outbox messages can have a failure reason")

    @property
    def assigned_agent(self) -> str | None:
        """Return the BDC agent assigned to the source draft."""
        return self.draft.assigned_agent

    @property
    def dealership(self) -> str | None:
        """Return the dealership assigned to the source draft."""
        return self.draft.dealership

    @property
    def language_preference(self) -> CustomerLanguage:
        """Return the customer's language from the source draft."""
        return self.draft.language_preference
