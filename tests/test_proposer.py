from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from crm_workflow.config import Settings
from crm_workflow.errors import DomainError
from crm_workflow.models import OrderRequest
from crm_workflow.proposer import Intent, check_consistency


def test_model_cannot_invent_even_valid_existing_customer_order_and_date():
    request = OrderRequest(message_id="unproven", message="Please reschedule my order")
    candidate = Intent(
        customer_reference="CUST-001",
        order_reference="ORD-1001",
        requested_date=date.today() + timedelta(days=10),
    )
    with pytest.raises(DomainError) as exc:
        check_consistency(request, candidate)
    assert exc.value.code == "MISSING_INFORMATION"


def test_model_cannot_choose_between_two_literal_identities():
    future = date.today() + timedelta(days=10)
    request = OrderRequest(message_id="ambiguous", message=f"CUST-001 or CUST-002; ORD-1001 for {future}")
    candidate = Intent(customer_reference="CUST-001", order_reference="ORD-1001", requested_date=future)
    with pytest.raises(DomainError):
        check_consistency(request, candidate)


def test_model_literal_proposal_has_source_evidence_without_permission_fields():
    future = date.today() + timedelta(days=10)
    request = OrderRequest(message_id="literal", message=f"Please move ORD-1001 for CUST-001 to {future}")
    candidate = Intent(customer_reference="CUST-001", order_reference="ORD-1001", requested_date=future)
    assert check_consistency(request, candidate) == candidate
    with pytest.raises(ValidationError):
        Intent.model_validate({**candidate.model_dump(), "approved": True, "discount": 100})


def test_external_model_transmission_requires_explicit_configuration():
    with pytest.raises(ValueError, match="External LLM"):
        Settings(proposer="ollama", llm_url="https://localhost.attacker.invalid")
    assert Settings(proposer="ollama", llm_url="http://127.0.0.1:11434").allow_external_llm is False
