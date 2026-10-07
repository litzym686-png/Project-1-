"""Pure routing of message drafts to existing BDC ownership."""

from dataclasses import replace
from collections.abc import Iterable

from app.models.customer import Customer
from app.models.message import MessageDraft, MessageStatus


def route_message_drafts(
    customers: Iterable[Customer],
    drafts: Iterable[MessageDraft | None],
) -> tuple[MessageDraft, ...]:
    """Assign drafts to matching customers for dealership review.

    ``None`` entries represent not-due customers and are skipped.
    """
    customers_by_name = _index_customers(customers)
    routed = []
    for draft in drafts:
        if draft is None:
            continue
        customer = customers_by_name.get(draft.customer_name)
        if customer is None:
            raise ValueError(f"No customer found for draft: {draft.customer_name}")
        routed.append(
            replace(
                draft,
                assigned_agent=customer.bdc_agent,
                dealership=customer.dealership,
                status=MessageStatus.REVIEW_READY.value,
            )
        )
    return tuple(routed)


def group_drafts_by_owner(
    drafts: Iterable[MessageDraft],
) -> dict[tuple[str, str], tuple[MessageDraft, ...]]:
    """Group review-ready drafts by assigned agent and dealership."""
    grouped: dict[tuple[str, str], list[MessageDraft]] = {}
    for draft in drafts:
        if not draft.assigned_agent or not draft.dealership:
            raise ValueError("Draft must be routed before grouping")
        owner = (draft.assigned_agent, draft.dealership)
        grouped.setdefault(owner, []).append(draft)
    return {owner: tuple(owner_drafts) for owner, owner_drafts in grouped.items()}


def _index_customers(customers: Iterable[Customer]) -> dict[str, Customer]:
    """Index customers and reject ambiguous names."""
    indexed: dict[str, Customer] = {}
    for customer in customers:
        if customer.customer_name in indexed:
            raise ValueError(f"Duplicate customer name: {customer.customer_name}")
        indexed[customer.customer_name] = customer
    return indexed
