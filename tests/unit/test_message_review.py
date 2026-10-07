from datetime import date

import pytest

from app.data.seed_customers import FICTIONAL_CUSTOMERS
from app.models.message import MessageStatus
from app.services.message_review import (
    approve_draft,
    get_review_ready_drafts,
    reject_draft,
)
from app.services.message_routing import route_message_drafts
from app.services.messaging import generate_service_reminder


def _routed_drafts():
    drafts = (
        generate_service_reminder(customer, date(2027, 1, 1))
        for customer in FICTIONAL_CUSTOMERS
    )
    return route_message_drafts(FICTIONAL_CUSTOMERS, drafts)


def test_each_agent_sees_only_assigned_review_ready_drafts():
    routed = _routed_drafts()

    for agent in {"Lucas", "Tracy", "Emily", "Ralphy", "Cassandra"}:
        queue = get_review_ready_drafts(routed, agent)
        assert len(queue) == 4
        assert all(draft.assigned_agent == agent for draft in queue)
        assert all(draft.status == MessageStatus.REVIEW_READY.value for draft in queue)


def test_all_seed_customers_remain_represented_in_review_queue():
    routed = _routed_drafts()
    queued = tuple(
        draft
        for agent in {"Lucas", "Tracy", "Emily", "Ralphy", "Cassandra"}
        for draft in get_review_ready_drafts(routed, agent)
    )

    assert len(queued) == 20
    assert {draft.customer_name for draft in queued} == {
        customer.customer_name for customer in FICTIONAL_CUSTOMERS
    }


def test_approval_changes_only_review_status():
    draft = _routed_drafts()[0]

    approved = approve_draft(draft)

    assert approved.status == MessageStatus.APPROVED.value
    assert approved.body == draft.body
    assert approved.rejection_reason is None


def test_rejection_requires_and_stores_reason():
    draft = _routed_drafts()[0]

    with pytest.raises(ValueError, match="reason is required"):
        reject_draft(draft, "  ")

    rejected = reject_draft(draft, "Please clarify the expected service date.")

    assert rejected.status == MessageStatus.REJECTED.value
    assert rejected.rejection_reason == "Please clarify the expected service date."


def test_rejected_draft_cannot_be_approved_or_return_to_review_queue():
    rejected = reject_draft(_routed_drafts()[0], "Incorrect contact details.")

    with pytest.raises(ValueError, match="expected 'review_ready'"):
        approve_draft(rejected)

    assert get_review_ready_drafts((rejected,), rejected.assigned_agent) == ()


def test_review_service_does_not_send_external_messages():
    draft = _routed_drafts()[0]

    approved = approve_draft(draft)

    assert approved.channel == draft.channel
    assert approved.contact == draft.contact
