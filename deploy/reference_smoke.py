"""One bounded, loopback-only API-to-worker reference workflow with original evidence."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--tokens", default=".local/tokens.json")
    parser.add_argument("--output", default="evidence-local/reference-smoke.json")
    args = parser.parse_args()
    if urlparse(args.url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("The reference exercise only permits an explicitly local demo endpoint")
    tokens = json.loads(Path(args.tokens).read_text())
    started = time.monotonic()
    with httpx.Client(base_url=args.url, timeout=10, trust_env=False) as client:

        def request(method, path, role="operator", *, expected=200, body=None):
            result = client.request(
                method, path, headers={"Authorization": f"Bearer {tokens[role]}"}, json=body
            )
            if result.status_code != expected:
                raise RuntimeError(f"{method} {path}: expected {expected}, observed {result.status_code}")
            return result.json()

        session = request("GET", "/api/v1/session")
        if session["profile"] != "demo":
            raise SystemExit(
                "Refusing a non-demo profile; vendor validation needs its separate authorised scope"
            )
        request("GET", "/health/ready")
        current_cases = request("GET", "/api/v1/cases")["items"]
        target_date = date.today() + timedelta(days=10)
        for previous in current_cases:
            observed = (previous.get("reconciliation") or {}).get("crm_order") or {}
            if observed.get("reference") == "ORD-1001":
                prior = date.fromisoformat(observed["requested_date"])
                target_date = (
                    prior + timedelta(days=1)
                    if prior < date.today() + timedelta(days=89)
                    else date.today() + timedelta(days=10)
                )
                break
        body = {
            "schema_version": "1.0",
            "message_id": f"reference-{uuid.uuid4()}",
            "customer_reference": "CUST-001",
            "order_reference": "ORD-1001",
            "requested_date": target_date.isoformat(),
        }
        case = request("POST", "/api/v1/cases", "requester", expected=202, body=body)
        duplicate = request("POST", "/api/v1/cases", "requester", expected=202, body=body)
        if duplicate["id"] != case["id"]:
            raise AssertionError("Repeated delivery created a second case")
        path = f"/api/v1/cases/{case['id']}"

        def wait_for(state):
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                value = request("GET", path)
                if value["state"] == state:
                    return value
                if value["state"] in {
                    "FAILED",
                    "RECONCILIATION_REQUIRED",
                    "ESCALATED",
                    "NEEDS_CLARIFICATION",
                    "APPROVAL_INVALIDATED",
                    "COMPENSATED",
                    "EXPIRED",
                }:
                    raise AssertionError(f"Unexpected terminal state: {value['state']}")
                time.sleep(0.2)
            raise TimeoutError(f"Case did not reach {state} within its bounded wait")

        waiting = wait_for("AWAITING_APPROVAL")
        approval = {"plan_hash": waiting["plan"]["hash"], "decision": "approve"}
        request("POST", path + "/approval", "requester", expected=403, body=approval)
        approved_at = time.monotonic()
        request("POST", path + "/approval", "approver", expected=202, body=approval)
        final = wait_for("COMPLETED")
        reconciled = request("POST", path + "/reconcile", body={})
        assert reconciled["reconciliation"]["matches"] is True
        assert len(final["effects"]) == 2
        report = {
            "profile": "local-reference-http",
            "captured_at": datetime.now(UTC).isoformat(),
            "provider_validation": False,
            "case_id": case["id"],
            "state": final["state"],
            "duplicate_delivery_same_case": True,
            "requester_approval_http_status": 403,
            "separate_approver": True,
            "effects": [
                {key: effect[key] for key in ("system", "status", "attempts")} for effect in final["effects"]
            ],
            "remote_readback_matches": True,
            "case_duration_seconds": time.monotonic() - started,
            "approval_to_completion_seconds": time.monotonic() - approved_at,
            "human_wait_seconds": 0,
            "human_wait_note": "Approval was automated by the synthetic test fixture; no real human latency measured.",
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"state": report["state"], "evidence": str(output), "provider_validation": False}))


if __name__ == "__main__":
    main()
