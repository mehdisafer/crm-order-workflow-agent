"""HTTP security and operator flows on the real core with the explicit synthetic systems.

These tests do not contact or validate Salesforce or MuleSoft. The service steps in
this module are invoked directly; Temporal execution is covered by the Temporal suite.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from crm_workflow.api import create_app
from crm_workflow.auth import Authenticator, authenticate_webhook
from crm_workflow.config import Settings
from crm_workflow.demo import seed_demo
from crm_workflow.errors import DomainError
from crm_workflow.runtime import build_runtime
from crm_workflow.store import Store


@pytest.fixture
def context(tmp_path):
    identities = {
        "requester": ("requester-a", "demo-industrial", ["requester"]),
        "approver": ("approver-b", "demo-industrial", ["approver"]),
        "operator": ("operator-c", "demo-industrial", ["operator"]),
        "self_approver": ("requester-a", "demo-industrial", ["requester", "approver"]),
        "other": ("other-person", "other-industrial", ["requester", "approver", "operator"]),
    }
    tokens = {name: secrets.token_urlsafe(32) for name in identities}
    principals = [
        {
            "token_sha256": hashlib.sha256(tokens[name].encode()).hexdigest(),
            "actor_id": actor_id,
            "tenant_id": tenant_id,
            "roles": roles,
        }
        for name, (actor_id, tenant_id, roles) in identities.items()
    ]
    auth_file = tmp_path / "principals.json"
    auth_file.write_text(json.dumps({"principals": principals}))
    secret = secrets.token_urlsafe(32)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'workflow.db'}",
        auth_file=str(auth_file),
        webhook_secret=SecretStr(secret),
        max_request_bytes=1024,
    )
    store = Store(settings.database_url)
    seed_demo(store)
    store.close()
    runtime = build_runtime(settings)
    ctx = SimpleNamespace(
        runtime=runtime,
        settings=settings,
        tokens=tokens,
        webhook_secret=secret,
        auth=lambda role: {"Authorization": f"Bearer {tokens[role]}"},
    )
    with TestClient(create_app(runtime), raise_server_exceptions=False) as client:
        ctx.client = client
        yield ctx
    asyncio.run(runtime.close())


def order_request(message_id="api-order-1"):
    return {
        "schema_version": "1.0",
        "message_id": message_id,
        "customer_reference": "CUST-001",
        "order_reference": "ORD-1001",
        "requested_date": (date.today() + timedelta(days=2)).isoformat(),
        "message": "Synthetic customer requests an earlier delivery.",
    }


def submit(context, *, role="requester", message_id="api-order-1"):
    response = context.client.post(
        "/api/v1/cases", json=order_request(message_id), headers=context.auth(role)
    )
    assert response.status_code == 202, response.text
    return response.json()


def sign(context, raw, *, timestamp=None):
    stamp = str(int(time.time())) if timestamp is None else str(timestamp)
    signature = hmac.new(
        context.webhook_secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    return {"Content-Type": "application/json", "X-P06-Timestamp": stamp, "X-P06-Signature": signature}


def test_public_ui_and_liveness_do_not_expose_tenant_data(context):
    client = context.client
    index = client.get("/")
    assert index.status_code == 200
    assert "Order exception desk" in index.text
    assert "default-src 'self'" in index.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in index.headers["content-security-policy"]
    assert index.headers["x-content-type-options"] == "nosniff"
    assert index.headers["cache-control"] == "no-store"
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").status_code == 401
    ready = client.get("/health/ready", headers=context.auth("operator"))
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "checks": {"transactional_storage": "available"}}
    assert client.get("/api/v1/openapi.json").status_code == 401
    assert client.get("/api/v1/openapi.json", headers=context.auth("requester")).status_code == 200


def test_principal_is_derived_only_from_bearer_config(context):
    client = context.client
    absent = client.get("/api/v1/session")
    assert absent.status_code == 401
    assert absent.headers["www-authenticate"] == "Bearer"
    assert client.get("/api/v1/session", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.get("/api/v1/session", headers={"Authorization": "Basic invalid"}).status_code == 401
    assert client.get(f"/api/v1/session?token={context.tokens['operator']}").status_code == 401
    response = client.get("/api/v1/session", headers=context.auth("requester"))
    assert response.json() == {
        "schema_version": "1.0",
        "actor": {"actor_id": "requester-a", "tenant_id": "demo-industrial", "roles": ["requester"]},
        "profile": "demo",
    }
    for field, value in [
        ("tenant_id", "other-industrial"),
        ("actor_id", "approver-b"),
        ("roles", ["approver"]),
    ]:
        response = client.post(
            "/api/v1/cases", headers=context.auth("requester"), json={**order_request(), field: value}
        )
        assert response.status_code == 422
    assert client.get("/api/v1/cases", headers=context.auth("requester")).json()["items"] == []


def test_validation_errors_omit_rejected_input_and_provider_details(context, monkeypatch, caplog):
    private_value = "private-text-must-not-be-reflected"
    response = context.client.post(
        "/api/v1/cases",
        headers=context.auth("requester"),
        json={**order_request(), "requested_date": private_value},
    )
    assert response.status_code == 422
    assert private_value not in response.text
    assert "input" not in response.text
    assert response.json()["error"]["violations"]

    async def broken_list(actor):
        raise RuntimeError(f"Remote provider returned a sensitive value: {private_value}")

    monkeypatch.setattr(context.runtime.service, "list_cases", broken_list)
    response = context.client.get("/api/v1/cases", headers=context.auth("requester"))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert private_value not in response.text
    assert private_value not in caplog.text
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    # Starlette's outer 500 handler normally re-raises errors to Uvicorn. The inner
    # boundary must contain the raw exception, including when transport re-raise is on.
    with TestClient(create_app(context.runtime), raise_server_exceptions=True) as strict_client:
        response = strict_client.get("/api/v1/cases", headers=context.auth("requester"))
    assert response.status_code == 500
    assert private_value not in response.text
    assert private_value not in caplog.text


def test_json_media_type_and_actual_body_size_are_enforced(context):
    wrong_type = context.client.post("/api/v1/cases", content="{}", headers=context.auth("requester"))
    assert wrong_type.status_code == 415
    oversized = json.dumps({**order_request(), "message": "x" * 1500}).encode()
    for content_length in [str(len(oversized)), "1"]:
        response = context.client.post(
            "/api/v1/cases",
            content=oversized,
            headers={
                **context.auth("requester"),
                "Content-Type": "application/json",
                "Content-Length": content_length,
            },
        )
        assert response.status_code == 413
    response = context.client.post(
        "/api/v1/cases",
        content=iter([oversized[:700], oversized[700:]]),
        headers={**context.auth("requester"), "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert context.runtime.store.list_cases("demo-industrial") == []


def test_duplicate_intake_keeps_one_case_and_cross_tenant_reads_are_denied(context):
    first = submit(context)
    duplicate = submit(context)
    assert duplicate["id"] == first["id"]
    assert (
        context.client.get("/api/v1/cases", headers=context.auth("requester")).json()["items"][0]["id"]
        == first["id"]
    )
    assert len(context.runtime.store.pending_outbox()) == 1
    changed = context.client.post(
        "/api/v1/cases",
        headers=context.auth("requester"),
        json={**order_request(), "message": "Changed payload"},
    )
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    hidden = context.client.get(f"/api/v1/cases/{first['id']}", headers=context.auth("other"))
    assert hidden.status_code == 404
    assert "ORD-1001" not in hidden.text
    assert context.client.get("/api/v1/cases", headers=context.auth("other")).json()["items"] == []
    other_case = submit(context, role="other")
    assert other_case["id"] != first["id"]
    assert other_case["tenant_id"] == "other-industrial"


def test_requester_cannot_self_approve_even_with_approver_role(context):
    first = submit(context)
    plan = asyncio.run(context.runtime.service.prepare(first["id"]))["plan"]
    route = f"/api/v1/cases/{first['id']}/approval"
    decision = {"plan_hash": plan["hash"], "decision": "approve"}
    for role in ["requester", "operator", "self_approver"]:
        assert context.client.post(route, headers=context.auth(role), json=decision).status_code == 403
    assert context.client.post(route, headers=context.auth("other"), json=decision).status_code == 404
    assert context.runtime.store.get_case(first["id"])["state"] == "AWAITING_APPROVAL"
    assert (
        context.client.post(
            "/api/v1/cases", headers=context.auth("approver"), json=order_request("forbidden")
        ).status_code
        == 403
    )


def test_api_approval_binds_plan_and_readback_exposes_later_drift(context):
    first = submit(context)
    service = context.runtime.service
    prepared = asyncio.run(service.prepare(first["id"]))
    route = f"/api/v1/cases/{first['id']}"
    decision = {"plan_hash": prepared["plan"]["hash"], "decision": "approve"}
    assert (
        context.client.post(
            f"{route}/approval", headers=context.auth("approver"), json={**decision, "plan_hash": "0" * 64}
        ).status_code
        == 409
    )
    assert (
        context.client.post(
            f"{route}/approval",
            headers=context.auth("approver"),
            json={**decision, "requested_date": "2099-01-01"},
        ).status_code
        == 422
    )
    approved = context.client.post(f"{route}/approval", headers=context.auth("approver"), json=decision)
    assert approved.status_code == 202
    assert approved.json()["state"] == "APPROVED"
    assert approved.json()["effects"] == []
    assert asyncio.run(service.execute_crm(first["id"]))["state"] == "CRM_APPLIED"
    assert asyncio.run(service.reserve_stock(first["id"]))["state"] == "STOCK_RESERVED"
    assert asyncio.run(service.verify(first["id"]))["state"] == "COMPLETED"
    detail = context.client.get(route, headers=context.auth("requester")).json()
    assert len(detail["effects"]) == 2
    assert detail["reconciliation"]["matches"] is True
    assert detail["reconciliation"]["provider_acceptance"] == "not_asserted"
    assert (
        context.client.post(f"{route}/reconcile", headers=context.auth("requester"), json={}).status_code
        == 403
    )
    assert (
        context.client.post(
            f"{route}/reconcile", headers=context.auth("operator"), json={"operation": "apply"}
        ).status_code
        == 422
    )
    assert (
        context.client.post(f"{route}/reconcile", headers=context.auth("operator"), json={}).json()[
            "reconciliation"
        ]["matches"]
        is True
    )
    human_date = (date.today() + timedelta(days=4)).isoformat()
    service.crm.human_change(prepared["plan"]["order"]["order_id"], human_date)
    drift = context.client.post(f"{route}/reconcile", headers=context.auth("operator"), json={}).json()
    assert drift["state"] == "COMPLETED"  # Historical workflow outcome stays visible.
    assert drift["reconciliation"]["matches"] is False
    assert drift["reconciliation"]["crm_order"]["requested_date"] == human_date
    assert len(drift["effects"]) == 2  # Reconciliation did not apply another change.


def test_webhook_signature_verifies_raw_bytes_then_applies_fixed_identity(context):
    raw = json.dumps(order_request("signed-webhook"), separators=(",", ":")).encode()
    headers = sign(context, raw)
    response = context.client.post("/api/v1/webhooks/requests", content=raw, headers=headers)
    assert response.status_code == 202
    case = response.json()
    assert case["requester_id"] == "n8n-trigger"
    assert case["tenant_id"] == "demo-industrial"
    repeated = context.client.post("/api/v1/webhooks/requests", content=raw, headers=headers)
    assert repeated.status_code == 202
    assert repeated.json()["id"] == case["id"]
    tampered = context.client.post("/api/v1/webhooks/requests", content=raw + b" ", headers=headers)
    assert tampered.status_code == 401
    malformed = context.client.post("/api/v1/webhooks/requests", content=b"{broken", headers=headers)
    assert malformed.status_code == 401  # Authentication precedes JSON parsing.
    alternate = {**headers, "X-P06-Signature": f"sha256={headers['X-P06-Signature']}"}
    assert context.client.post("/api/v1/webhooks/requests", content=raw, headers=alternate).status_code == 202
    for delta in [-600, 600]:
        stale = sign(context, raw, timestamp=int(time.time()) + delta)
        assert context.client.post("/api/v1/webhooks/requests", content=raw, headers=stale).status_code == 401
    injected = json.dumps({**order_request("signed-injection"), "tenant_id": "other-industrial"}).encode()
    assert (
        context.client.post(
            "/api/v1/webhooks/requests", content=injected, headers=sign(context, injected)
        ).status_code
        == 422
    )
    assert context.runtime.store.list_cases("other-industrial") == []


def test_webhook_is_disabled_without_a_secret():
    with pytest.raises(DomainError) as result:
        authenticate_webhook(raw=b"{}", timestamp=str(int(time.time())), signature="0" * 64, secret="")
    assert result.value.status_code == 503


def test_duplicate_authentication_hash_fails_closed(tmp_path):
    digest = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    principal = {
        "token_sha256": digest,
        "actor_id": "one",
        "tenant_id": "demo-industrial",
        "roles": ["requester"],
    }
    path = tmp_path / "invalid-principals.json"
    path.write_text(
        json.dumps({"principals": [principal, {**principal, "actor_id": "two", "roles": ["approver"]}]})
    )
    with pytest.raises(RuntimeError) as result:
        Authenticator(path)
    assert str(result.value) == "Authentication configuration is missing or invalid"
    assert digest not in str(result.value)


def test_metrics_are_operator_only_and_do_not_include_case_ids(context):
    first = submit(context)
    submit(context, role="other", message_id="other-case")
    context.client.get(f"/api/v1/cases/{first['id']}", headers=context.auth("requester"))
    assert context.client.get("/metrics").status_code == 401
    assert context.client.get("/metrics", headers=context.auth("requester")).status_code == 403
    response = context.client.get("/metrics", headers=context.auth("operator"))
    assert response.status_code == 200, response.text
    assert "text/plain" in response.headers["content-type"]
    assert 'p06_cases{state="RECEIVED"} 1.0' in response.text
    assert "p06_outbox_pending 1.0" in response.text
    assert 'route="/api/v1/cases/{case_id}"' in response.text
    assert first["id"] not in response.text
    assert "demo-industrial" not in response.text
    assert "other-industrial" not in response.text
