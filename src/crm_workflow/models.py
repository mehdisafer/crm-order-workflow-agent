from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Actor(StrictModel):
    actor_id: Identifier
    tenant_id: Identifier
    roles: list[Literal["requester", "approver", "operator"]]


class OrderRequest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    message_id: Identifier
    customer_reference: Identifier | None = None
    order_reference: Identifier | None = None
    requested_date: date | None = None
    message: str = Field(default="", max_length=4000)


class ApprovalRequest(StrictModel):
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["approve", "reject"]


class Customer(StrictModel):
    customer_id: Identifier
    tenant_id: Identifier
    reference: Identifier
    name: str = Field(max_length=200)


class Order(StrictModel):
    order_id: Identifier
    tenant_id: Identifier
    customer_id: Identifier
    reference: Identifier
    sku: Identifier
    quantity: int = Field(gt=0, le=100000)
    requested_date: date
    revision: int = Field(ge=1)
    crm_url: str = Field(max_length=500)
    last_effect_key: str | None = None

    @field_validator("crm_url")
    @classmethod
    def safe_link(cls, value: str) -> str:
        if not (value.startswith("https://") or value.startswith("demo://")):
            raise ValueError("CRM object links must use HTTPS or the explicit demo scheme")
        return value


class Availability(StrictModel):
    tenant_id: Identifier
    sku: Identifier
    available: int = Field(ge=0)
    revision: int = Field(ge=1)


class ActionPlan(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: Identifier
    tenant_id: Identifier
    requester_id: Identifier
    customer: Customer
    order: Order
    availability: Availability
    operation: Literal["change_delivery_date"] = "change_delivery_date"
    requested_date: date
    fields: list[Literal["requested_date"]] = Field(default_factory=lambda: ["requested_date"])
    risk: Literal["controlled_order_change"] = "controlled_order_change"
    compensation_allowed: bool = True
    expires_at: datetime
    policy_version: Literal["1.0"] = "1.0"


class StoredPlan(ActionPlan):
    hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ApprovalRecord(ApprovalRequest):
    actor_id: Identifier
    tenant_id: Identifier
    approved_at: datetime


class CaseEvent(StrictModel):
    id: Identifier
    case_id: Identifier
    event_type: str = Field(min_length=1, max_length=100)
    payload: dict
    created_at: datetime


class EffectEvidence(StrictModel):
    effect_key: str = Field(min_length=1, max_length=150)
    case_id: Identifier
    system: Literal["crm", "erp"]
    operation: Literal["change_delivery_date", "compensate_delivery_date", "reserve_stock"]
    status: Literal["PREPARED", "UNKNOWN", "APPLIED", "COMPENSATED", "REJECTED"]
    request_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    request: dict
    before: dict | None = None
    after: dict | None = None
    attempts: int = Field(ge=0)


class CaseResponse(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    id: Identifier
    correlation_id: Identifier
    tenant_id: Identifier
    requester_id: Identifier
    request: OrderRequest
    state: Literal[
        "RECEIVED",
        "AWAITING_APPROVAL",
        "APPROVED",
        "REJECTED",
        "NEEDS_CLARIFICATION",
        "ESCALATED",
        "APPROVAL_INVALIDATED",
        "CRM_APPLIED",
        "STOCK_RESERVED",
        "COMPLETED",
        "COMPENSATED",
        "RECONCILIATION_REQUIRED",
        "FAILED",
        "EXPIRED",
    ]
    reason: str
    plan: StoredPlan | None = None
    approval: ApprovalRecord | None = None
    created_at: datetime
    updated_at: datetime
    api_calls: int = Field(ge=0)
    effects: list[EffectEvidence]
    events: list[CaseEvent]
    reconciliation: dict | None = None
    compensation_reason: str | None = None


def utcnow() -> datetime:
    return datetime.now(UTC)


def timestamp() -> str:
    return utcnow().isoformat()


def canonical_hash(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


TERMINAL_STATES = frozenset(
    {
        "COMPLETED",
        "COMPENSATED",
        "RECONCILIATION_REQUIRED",
        "NEEDS_CLARIFICATION",
        "ESCALATED",
        "APPROVAL_INVALIDATED",
        "FAILED",
        "EXPIRED",
        "REJECTED",
    }
)
