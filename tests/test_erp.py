"""Real ERP ASGI application and HTTPERP adapter, backed by a separate transaction store.

No responses are fabricated in this suite. The ERP itself is an original synthetic
system; these results make no statement about Salesforce or MuleSoft permissions.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from crm_workflow.config import Settings
from crm_workflow.demo import DemoCRM, DemoERP, seed_demo
from crm_workflow.erp import create_app
from crm_workflow.errors import DomainError
from crm_workflow.gateways import HTTPERP
from crm_workflow.models import Actor, ApprovalRequest, OrderRequest
from crm_workflow.proposer import RulesProposer
from crm_workflow.service import CaseService
from crm_workflow.store import Store


@pytest.fixture
async def erp_context(tmp_path):
    token = secrets.token_urlsafe(32)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'separate-erp.db'}",
        erp_token=SecretStr(token),
        max_request_bytes=1024,
    )
    store = Store(settings.database_url)
    seed_demo(store)
    app = create_app(store, settings)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    adapter = HTTPERP("http://erp.test", token, transport=transport)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://erp.test") as client:
            yield SimpleNamespace(
                app=app,
                client=client,
                adapter=adapter,
                store=store,
                settings=settings,
                headers={"Authorization": f"Bearer {token}", "X-Correlation-ID": "erp-test-correlation"},
            )
    await adapter.close()
    store.close()


def reservation_request(key="erp-test:stock"):
    return {
        "effect_key": key,
        "tenant_id": "demo-industrial",
        "order_id": "order-1001",
        "sku": "SKU-001",
        "quantity": 10,
        "expected_revision": 1,
        "approved_plan_hash": "a" * 64,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
    }


async def test_http_adapter_reserves_once_and_reconciles_a_receipt(erp_context):
    adapter = erp_context.adapter
    before = await adapter.availability("demo-industrial", "SKU-001")
    assert before["available"] == 100
    payload = reservation_request()
    assert await adapter.reservation("demo-industrial", payload["effect_key"]) is None
    first = await adapter.reserve(payload, "correlation-1")
    replay = await adapter.reserve(payload, "correlation-1")
    receipt = await adapter.reservation("demo-industrial", payload["effect_key"])
    after = await adapter.availability("demo-industrial", "SKU-001")
    assert first["status"] == "reserved"
    assert first["replayed"] is False
    assert replay["replayed"] is True
    assert receipt == first
    assert after["available"] == 90
    assert after["revision"] == 2
    with pytest.raises(DomainError) as changed:
        await adapter.reserve({**payload, "quantity": 20}, "correlation-2")
    assert changed.value.code == "STATE_CHANGED"
    assert (await adapter.availability("demo-industrial", "SKU-001"))["available"] == 90


async def test_erp_technical_credential_cannot_cross_tenants(erp_context):
    adapter = erp_context.adapter
    with pytest.raises(DomainError) as denied:
        await adapter.availability("other-industrial", "SKU-001")
    assert denied.value.status_code == 404
    response = await erp_context.client.post(
        "/v1/reservations",
        headers=erp_context.headers,
        json={**reservation_request(), "tenant_id": "other-industrial"},
    )
    assert response.status_code == 404
    assert "other-industrial" not in response.text
    assert "SKU-001" not in response.text
    assert await adapter.reservation("other-industrial", "erp-test:stock") is None
    other_stock = await DemoERP(erp_context.store).availability("other-industrial", "SKU-001")
    assert other_stock["available"] == 100
    for headers in [{}, {"Authorization": "Bearer invalid"}, {"Authorization": "Basic invalid"}]:
        response = await erp_context.client.get(
            "/v1/availability/SKU-001?tenant_id=demo-industrial", headers=headers
        )
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


async def test_erp_expiry_cas_and_extra_fields_are_checked_before_write(erp_context):
    payload = reservation_request()
    for changes, status in [
        ({"expires_at": (datetime.now(UTC) - timedelta(seconds=5)).isoformat()}, 409),
        ({"expected_revision": 8}, 409),
        ({"quantity": 101}, 409),
        ({"quantity": 0}, 422),
        ({"expires_at": "2030-01-01T12:00:00"}, 422),
        ({"allowed": True}, 422),
    ]:
        response = await erp_context.client.post(
            "/v1/reservations", headers=erp_context.headers, json={**payload, **changes}
        )
        assert response.status_code == status, response.text
    assert (await erp_context.adapter.availability("demo-industrial", "SKU-001"))["available"] == 100
    assert await erp_context.adapter.reservation("demo-industrial", payload["effect_key"]) is None


async def test_erp_json_limits_and_errors_do_not_reflect_input(erp_context, monkeypatch, caplog):
    confidential = "do-not-reflect-this-input-value"
    invalid = await erp_context.client.post(
        "/v1/reservations",
        headers=erp_context.headers,
        json={**reservation_request(), "quantity": confidential},
    )
    assert invalid.status_code == 422
    assert confidential not in invalid.text
    assert "input" not in invalid.text
    wrong_type = await erp_context.client.post("/v1/reservations", headers=erp_context.headers, content="{}")
    assert wrong_type.status_code == 415
    raw = json.dumps({**reservation_request(), "unexpected": "x" * 1500}).encode()
    oversized = await erp_context.client.post(
        "/v1/reservations",
        content=raw,
        headers={**erp_context.headers, "Content-Type": "application/json", "Content-Length": "1"},
    )
    assert oversized.status_code == 413

    async def broken_availability(tenant_id, sku):
        raise RuntimeError(confidential)

    monkeypatch.setattr(erp_context.app.state.erp, "availability", broken_availability)
    failed = await erp_context.client.get(
        "/v1/availability/SKU-001?tenant_id=demo-industrial", headers=erp_context.headers
    )
    assert failed.status_code == 500
    assert confidential not in failed.text
    assert confidential not in caplog.text
    assert failed.headers["cache-control"] == "no-store"


async def test_core_saga_uses_http_erp_database_without_local_fallback(erp_context, tmp_path):
    workflow_store = Store(f"sqlite:///{tmp_path / 'separate-workflow.db'}")
    seed_demo(workflow_store)
    service = CaseService(
        workflow_store, DemoCRM(workflow_store), erp_context.adapter, RulesProposer(), Settings()
    )
    requester = Actor(actor_id="sender", tenant_id="demo-industrial", roles=["requester"])
    approver = Actor(actor_id="reviewer", tenant_id="demo-industrial", roles=["approver"])
    try:
        case = await service.create_case(
            OrderRequest(
                message_id="http-erp-saga",
                customer_reference="CUST-001",
                order_reference="ORD-1001",
                requested_date=date.today() + timedelta(days=3),
            ),
            requester,
        )
        case = await service.prepare(case["id"])
        assert case["state"] == "AWAITING_APPROVAL"
        case = await service.approve(
            case["id"], ApprovalRequest(plan_hash=case["plan"]["hash"], decision="approve"), approver
        )
        assert (await service.execute_crm(case["id"]))["state"] == "CRM_APPLIED"
        assert (await service.reserve_stock(case["id"]))["state"] == "STOCK_RESERVED"
        result = await service.verify(case["id"])
        assert result["state"] == "COMPLETED"
        assert result["reconciliation"]["matches"] is True
        assert result["reconciliation"]["reservation"]["effect_key"] == f"{case['id']}:stock"
        assert (await erp_context.adapter.availability("demo-industrial", "SKU-001"))["available"] == 90
        # The similarly named local fixture remains untouched: HTTPERP made the reservation.
        assert (await DemoERP(workflow_store).availability("demo-industrial", "SKU-001"))["available"] == 100
    finally:
        workflow_store.close()


async def test_erp_startup_refuses_a_weak_technical_credential(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'invalid-erp.db'}", erp_token=SecretStr("short"))
    app = create_app(settings=settings)
    with pytest.raises(RuntimeError, match="externally supplied random technical token"):
        async with app.router.lifespan_context(app):
            pytest.fail("The ERP must not start without a sufficiently long external credential")
