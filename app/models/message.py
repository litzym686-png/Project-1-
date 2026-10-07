"""Typed fictional message drafts with no sending behavior."""

from dataclasses import dataclass
from enum import Enum


class MessageChannel(str, Enum):
    """Supported draft destinations."""

    EMAIL = "email"
    SMS = "sms"


class MessageStatus(str, Enum):
    """Review lifecycle states for a message draft."""

    DRAFT = "draft"
    REVIEW_READY = "review_ready"


@dataclass(frozen=True)
class MessageDraft:
    """A service reminder prepared for review without sending behavior."""

    customer_name: str
    contact: str
    channel: MessageChannel
    body: str
    status: str = MessageStatus.DRAFT.value
    assigned_agent: str | None = None
    dealership: str | None = None

    def __post_init__(self) -> None:
        if not self.customer_name.strip():
            raise ValueError("Message customer name is required")
        if not self.contact.strip():
            raise ValueError("Message contact is required")
        if not self.body.strip():
            raise ValueError("Message body is required")
        if self.status not in {status.value for status in MessageStatus}:
            raise ValueError("Message status is not recognized")
        if self.assigned_agent is not None and not self.assigned_agent.strip():
            raise ValueError("Assigned agent cannot be blank")
        if self.dealership is not None and not self.dealership.strip():
            raise ValueError("Dealership cannot be blank")
