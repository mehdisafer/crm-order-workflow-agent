"""Regressions found during cross-review, using isolated data and explicit fault injection.

The transport test exercises the client's stream boundary. It is not vendor evidence.
The remaining tests use the actual core/store and the original synthetic systems.
"""

from __future__ import annotations

import json
import secrets
from datetime import date, timedelta

import httpx
import pytest

from crm_workflow.config import Settings
from crm_workflow.demo import DemoCRM, DemoERP, seed_demo
from crm_workflow.errors import DomainError, TransientError, UnknownOutcome
from crm_workflow.gateways import HTTPSystem
from crm_workflow.models import Actor, ApprovalRequest, OrderRequest
from crm_workflow.proposer import RulesProposer
from crm_workflow.service import CaseService
from crm_workflow.store import Store

REQUESTER = Actor(actor_id="review-requester", tenant_id="demo-industrial", roles=["requester"])
APPROVER = Actor(actor_id="review-approver", tenant_id="demo-industrial", roles=["approver"])
OPERATOR = Actor(actor_id="review-operator", tenant_id="demo-industrial", roles=["operator"])


@pytest.fixture
def service(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'review.db'}")
    seed_demo(store)
    yield CaseService(store, DemoCRM(store), DemoERP(store), RulesProposer(), Settings())
    store.close()


async def prepare(service):
    case = await service.create_case(
        OrderRequest(
            message_id="review-regression",
            customer_reference="CUST-001",
            order_reference="ORD-1001",
            requested_date=date.today() + timedelta(days=10),
        ),
        REQUESTER,
    )
    result = await service.prepare(case["id"])
    assert result["state"] == "AWAITING_APPROVAL"
    return result


async def approve(service, prepared=None):
    prepared = prepared or await prepare(service)
    result = await service.approve(
        prepared["id"], ApprovalRequest(plan_hash=prepared["plan"]["hash"], decision="approve"), APPROVER
    )
    assert result["state"] == "APPROVED"
    return result


async def complete(service):
    case = await approve(service)
    assert (await service.execute_crm(case["id"]))["state"] == "CRM_APPLIED"
    assert (await service.reserve_stock(case["id"]))["state"] == "STOCK_RESERVED"
    result = await service.verify(case["id"])
    assert result["state"] == "COMPLETED"
    return result


async def test_compensated_case_reconciles_against_restore_and_no_reservation(service):
    case = await approve(service)
    before = case["plan"]["order"]
    assert (await service.execute_crm(case["id"]))["state"] == "CRM_APPLIED"
    service.erp.change_stock("demo-industrial", "SKU-001", 0)
    with pytest.raises(DomainError) as refusal:
        await service.reserve_stock(case["id"])
    assert refusal.value.code == "STOCK_CHANGED"
    restored = await service.compensate(case["id"], "Stock became unavailable after CRM change")
    assert restored["state"] == "COMPENSATED"
    checked = await service.reconcile(case["id"], OPERATOR)
    assert checked["state"] == "COMPENSATED"
    assert checked["reconciliation"]["matches"] is True
    assert checked["reconciliation"]["expected_outcome"] == "compensated"
    assert checked["reconciliation"]["reservation"] is None
    assert checked["reconciliation"]["crm_order"]["requested_date"] == before["requested_date"]
    assert checked["reconciliation"]["crm_order"]["revision"] == before["revision"] + 2
    assert len([effect for effect in checked["effects"] if effect["system"] == "crm"]) == 2


@pytest.mark.parametrize("system", ["crm", "erp"])
async def test_misrouted_readback_never_persists_or_exposes_foreign_scope(service, monkeypatch, system):
    case = await complete(service)
    original_readback = case["reconciliation"]
    private_marker = "FOREIGN-SYNTHETIC-PRIVATE-REFERENCE"
    if system == "crm":
        foreign = await service.crm.order("other-industrial", "order-1001-other")
        foreign = {**foreign, "reference": private_marker}

        async def misrouted_order(tenant_id, order_id):
            return foreign

        monkeypatch.setattr(service.crm, "order", misrouted_order)
    else:
        foreign = {
            **case["reconciliation"]["reservation"],
            "tenant_id": "other-industrial",
            "order_id": "order-1001-other",
            "sku": private_marker,
        }

        async def misrouted_reservation(tenant_id, key):
            return foreign

        monkeypatch.setattr(service.erp, "reservation", misrouted_reservation)
    with pytest.raises(DomainError) as failure:
        await service.reconcile(case["id"], OPERATOR)
    assert failure.value.code == "REMOTE_IDENTITY_MISMATCH"
    assert private_marker not in str(failure.value)
    observed = await service.get_case(case["id"], OPERATOR)
    assert observed["reconciliation"] == original_readback
    assert private_marker not in json.dumps(observed)
    assert "other-industrial" not in json.dumps(observed)


async def test_missing_receipt_for_unknown_stock_write_does_not_authorise_compensation(service, monkeypatch):
    case = await approve(service)
    assert (await service.execute_crm(case["id"]))["state"] == "CRM_APPLIED"
    original_reserve = service.erp.reserve

    async def interrupted_write(payload, correlation_id):
        raise UnknownOutcome("Injected response loss; a remote transaction may still be in flight")

    monkeypatch.setattr(service.erp, "reserve", interrupted_write)
    with pytest.raises(UnknownOutcome):
        await service.reserve_stock(case["id"])
    key = f"{case['id']}:stock"
    assert service.store.effect(key)["status"] == "UNKNOWN"
    assert await service.erp.reservation("demo-industrial", key) is None
    result = await service.compensate(case["id"], "The bounded stock retry was interrupted")
    assert result["state"] == "RECONCILIATION_REQUIRED"
    assert "STOCK_OUTCOME_UNCERTAIN" in result["reason"]
    assert service.store.effect(f"{case['id']}:crm:compensate") is None
    current = await service.crm.order("demo-industrial", case["plan"]["order"]["order_id"])
    assert current["requested_date"] == case["plan"]["requested_date"]
    # Model a delayed remote commit after the receipt lookup returned absent.
    await original_reserve(service.store.effect(key)["request"], case["correlation_id"])
    later = await service.reconcile(case["id"], OPERATOR)
    assert later["reconciliation"]["matches"] is True
    assert (
        later["state"] == "RECONCILIATION_REQUIRED"
    )  # The earlier uncertain outcome is retained as history.


async def test_expiry_stale_read_cannot_overwrite_a_committed_approval(service, monkeypatch):
    waiting = await prepare(service)
    approved = await approve(service, waiting)
    real_get_case = service.store.get_case
    stale_once = True

    def stale_snapshot(case_id):
        nonlocal stale_once
        if stale_once and case_id == waiting["id"]:
            stale_once = False
            return waiting
        return real_get_case(case_id)

    # Deterministic interleaving: expire read AWAITING_APPROVAL before the approval commit,
    # then attempts its transition against the actually committed APPROVED database row.
    monkeypatch.setattr(service.store, "get_case", stale_snapshot)
    result = await service.expire(waiting["id"])
    assert result["state"] == "APPROVED"
    assert result["approval"] == approved["approval"]
    persisted = real_get_case(waiting["id"])
    assert persisted["state"] == "APPROVED"
    assert not any(event["event_type"] == "case.expired" for event in persisted["events"])
    decisions = [event for event in service.store.pending_outbox() if event["kind"] == "workflow.decision"]
    assert len(decisions) == 1


@pytest.mark.parametrize("method,error_type", [("GET", TransientError), ("POST", UnknownOutcome)])
async def test_stream_limit_stops_reading_and_redacts_upstream_content(method, error_type):
    marker = b"synthetic-upstream-private-marker"

    class OversizedStream(httpx.AsyncByteStream):
        def __init__(self):
            self.yielded = 0
            self.closed = False

        async def __aiter__(self):
            for _ in range(100):
                self.yielded += 1
                yield marker + b"x" * (65536 - len(marker))

        async def aclose(self):
            self.closed = True

    stream = OversizedStream()
    calls = 0

    def upstream(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers={"Content-Type": "application/json"}, stream=stream)

    client = HTTPSystem(
        "https://synthetic.invalid", secrets.token_urlsafe(32), transport=httpx.MockTransport(upstream)
    )
    try:
        with pytest.raises(error_type) as failure:
            await client.request(
                method, "/oversized", **({"json": {"effect_key": "test"}} if method == "POST" else {})
            )
        assert stream.yielded == 17  # 1 MiB plus one bounded chunk; never consumes the remaining 83 chunks.
        assert stream.closed is True
        assert calls == 1
        assert marker.decode() not in str(failure.value)
    finally:
        await client.close()
