"""Pure review operations for routed fictional message drafts."""

from collections.abc import Iterable
from dataclasses import replace

from app.models.customer import BDC_AGENTS
from app.models.message import MessageDraft, MessageStatus


def get_review_ready_drafts(
    drafts: Iterable[MessageDraft],
    assigned_agent: str,
) -> tuple[MessageDraft, ...]:
    """Return only review-ready drafts assigned to the requested agent."""
    _validate_agent(assigned_agent)
    return tuple(
        draft
        for draft in drafts
        if draft.assigned_agent == assigned_agent
        and draft.status == MessageStatus.REVIEW_READY.value
    )


def approve_draft(draft: MessageDraft) -> MessageDraft:
    """Approve a review-ready draft without sending it."""
    _require_review_ready(draft)
    return replace(draft, status=MessageStatus.APPROVED.value)


def reject_draft(draft: MessageDraft, reason: str) -> MessageDraft:
    """Reject a review-ready draft with a required explanation."""
    _require_review_ready(draft)
    if not reason.strip():
        raise ValueError("Rejection reason is required")
    return replace(
        draft,
        status=MessageStatus.REJECTED.value,
        rejection_reason=reason,
    )


def _require_review_ready(draft: MessageDraft) -> None:
    """Reject review actions that do not start from the review queue."""
    if draft.status != MessageStatus.REVIEW_READY.value:
        raise ValueError(
            f"Cannot review a draft with status '{draft.status}'; "
            "expected 'review_ready'"
        )


def _validate_agent(assigned_agent: str) -> None:
    """Reject lookups for agents outside the dealership's BDC roster."""
    if assigned_agent not in BDC_AGENTS:
        raise ValueError(f"BDC agent is not recognized: {assigned_agent}")
