from dataclasses import replace

import pytest

from app.models.customer import CustomerLanguage
from app.models.message import MessageChannel, MessageDraft, MessageStatus
from app.models.outbox import OutboxStatus
from app.services.message_outbox import (
    mark_delivery_failed,
    mark_simulated_sent,
    queue_approved_message,
)


def _approved_draft(
    *,
    customer_name: str = "Test Customer",
    dealership: str = "Kia",
    assigned_agent: str = "Lucas",
    language: CustomerLanguage = CustomerLanguage.ENGLISH,
) -> MessageDraft:
    return MessageDraft(
        customer_name=customer_name,
        contact=f"{customer_name.replace(' ', '.').lower()}@example.test",
        channel=MessageChannel.EMAIL,
        body="Reminder body",
        status=MessageStatus.APPROVED.value,
        assigned_agent=assigned_agent,
        dealership=dealership,
        language_preference=language,
    )


@pytest.mark.parametrize(
    "status",
    (
        MessageStatus.DRAFT.value,
        MessageStatus.REVIEW_READY.value,
        MessageStatus.REJECTED.value,
    ),
)
def test_only_approved_messages_can_be_queued(status):
    draft = replace(
        _approved_draft(),
        status=status,
        rejection_reason="Not needed" if status == MessageStatus.REJECTED.value else None,
    )

    with pytest.raises(ValueError, match="Only approved messages can be queued"):
        queue_approved_message(draft)


def test_queue_preserves_ownership_and_language():
    draft = _approved_draft(
        dealership="Chevrolet",
        assigned_agent="Tracy",
        language=CustomerLanguage.SPANISH,
    )

    queued = queue_approved_message(draft)

    assert queued.status is OutboxStatus.QUEUED
    assert queued.dealership == "Chevrolet"
    assert queued.assigned_agent == "Tracy"
    assert queued.language_preference is CustomerLanguage.SPANISH
    assert queued.draft is draft


def test_unrouted_approved_messages_cannot_be_queued():
    draft = replace(_approved_draft(), assigned_agent=None, dealership=None)

    with pytest.raises(ValueError, match="Only routed messages can be queued"):
        queue_approved_message(draft)


def test_queue_transitions_to_simulated_sent():
    queued = queue_approved_message(_approved_draft())

    sent = mark_simulated_sent(queued)

    assert sent.status is OutboxStatus.SIMULATED_SENT
    assert sent.draft == queued.draft
    assert sent.failure_reason is None


def test_queue_transitions_to_failed_with_reason():
    queued = queue_approved_message(_approved_draft())

    failed = mark_delivery_failed(queued, "Simulated provider unavailable.")

    assert failed.status is OutboxStatus.FAILED
    assert failed.failure_reason == "Simulated provider unavailable."


def test_invalid_delivery_transitions_and_blank_failure_are_rejected():
    queued = queue_approved_message(_approved_draft())
    sent = mark_simulated_sent(queued)
    failed = mark_delivery_failed(queued, "Simulated timeout.")

    with pytest.raises(ValueError, match="expected 'queued'"):
        mark_simulated_sent(sent)
    with pytest.raises(ValueError, match="expected 'queued'"):
        mark_delivery_failed(failed, "Retry")
    with pytest.raises(ValueError, match="Failure reason is required"):
        mark_delivery_failed(queued, "  ")


def test_duplicate_message_cannot_be_queued():
    draft = _approved_draft()
    queued = queue_approved_message(draft)

    with pytest.raises(ValueError, match="already queued"):
        queue_approved_message(draft, (queued,))


def test_outbox_does_not_cross_dealership_or_agent_boundaries():
    kia_message = queue_approved_message(
        _approved_draft(
            customer_name="Kia Customer",
            dealership="Kia",
            assigned_agent="Lucas",
        )
    )
    chevrolet_message = queue_approved_message(
        _approved_draft(
            customer_name="Chevrolet Customer",
            dealership="Chevrolet",
            assigned_agent="Tracy",
        ),
        (kia_message,),
    )

    assert (kia_message.dealership, kia_message.assigned_agent) == ("Kia", "Lucas")
    assert (chevrolet_message.dealership, chevrolet_message.assigned_agent) == (
        "Chevrolet",
        "Tracy",
    )
