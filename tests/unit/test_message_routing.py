from datetime import date

from app.data.seed_customers import FICTIONAL_CUSTOMERS
from app.models.message import MessageStatus
from app.services.message_routing import group_drafts_by_owner, route_message_drafts
from app.services.messaging import generate_service_reminder


def test_all_seed_drafts_route_to_existing_agents_and_dealerships():
    drafts = (
        generate_service_reminder(customer, date(2027, 1, 1))
        for customer in FICTIONAL_CUSTOMERS
    )

    routed = route_message_drafts(FICTIONAL_CUSTOMERS, drafts)
    grouped = group_drafts_by_owner(routed)

    assert len(routed) == 20
    assert {draft.dealership for draft in routed} == {"Chevrolet", "Kia"}
    assert all(draft.status == MessageStatus.REVIEW_READY.value for draft in routed)
    assert all(draft.assigned_agent for draft in routed)
    assert {
        agent: sum(draft.assigned_agent == agent for draft in routed)
        for agent in {"Lucas", "Tracy", "Emily", "Ralphy", "Cassandra"}
    } == {
        "Lucas": 4,
        "Tracy": 4,
        "Emily": 4,
        "Ralphy": 4,
        "Cassandra": 4,
    }
    assert sum(len(owner_drafts) for owner_drafts in grouped.values()) == 20


def test_not_due_customer_without_draft_is_skipped():
    drafts = [None] + [
        generate_service_reminder(FICTIONAL_CUSTOMERS[0], date(2025, 1, 1))
    ]

    assert route_message_drafts(FICTIONAL_CUSTOMERS, drafts) == ()


def test_routing_does_not_send_or_change_message_content():
    draft = generate_service_reminder(FICTIONAL_CUSTOMERS[0], date(2026, 10, 7))
    routed = route_message_drafts(FICTIONAL_CUSTOMERS, [draft])[0]

    assert routed.body == draft.body
    assert routed.contact == draft.contact
