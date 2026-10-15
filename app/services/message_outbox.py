"""Pure operations for the simulated outbound message queue."""

from collections.abc import Iterable
from dataclasses import replace

from app.models.message import MessageDraft, MessageStatus
from app.models.outbox import OutboxMessage, OutboxStatus


def queue_approved_message(
    draft: MessageDraft,
    existing_messages: Iterable[OutboxMessage] = (),
) -> OutboxMessage:
    """Queue one approved, routed draft without sending it."""
    if draft.status != MessageStatus.APPROVED.value:
        raise ValueError("Only approved messages can be queued")
    if not draft.assigned_agent or not draft.dealership:
        raise ValueError("Only routed messages can be queued")
    if any(message.draft == draft for message in existing_messages):
        raise ValueError("Message is already queued in the outbox")
    return OutboxMessage(draft=draft)


def mark_simulated_sent(message: OutboxMessage) -> OutboxMessage:
    """Complete simulated delivery for a queued message."""
    _require_queued(message)
    return replace(message, status=OutboxStatus.SIMULATED_SENT)


def mark_delivery_failed(message: OutboxMessage, reason: str) -> OutboxMessage:
    """Record a failed simulated delivery with an explanation."""
    _require_queued(message)
    if not reason.strip():
        raise ValueError("Failure reason is required")
    return replace(
        message,
        status=OutboxStatus.FAILED,
        failure_reason=reason,
    )


def _require_queued(message: OutboxMessage) -> None:
    """Reject delivery transitions from terminal states."""
    if message.status != OutboxStatus.QUEUED:
        raise ValueError(
            f"Cannot transition outbox message from '{message.status.value}'; "
            "expected 'queued'"
        )
