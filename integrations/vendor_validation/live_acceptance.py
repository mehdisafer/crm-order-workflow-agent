#!/usr/bin/env python3
"""Execute bounded, real API -> Temporal -> MuleSoft -> Salesforce qualification.

This command never installs credentials, creates accounts, deploys services, or
silently changes profile. Two synthetic cases are submitted; one changes a date
and reserves inventory, the other must invalidate an approved stale snapshot.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import ssl
import subprocess
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from uuid import uuid4

import httpx


class QualificationError(RuntimeError):
    pass


def remaining(deadline: float, cap: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise QualificationError(
            "Global qualification deadline expired; retain case IDs and reconcile before retrying"
        )
    return min(seconds, cap)


class Client:
    def __init__(self, origin: str, token: str, deadline: float, ca_file: str | None = None):
        parsed = urlsplit(origin)
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise QualificationError("An endpoint must be an origin with no credentials or path")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
        ):
            raise QualificationError("Only HTTPS or loopback HTTP endpoints are accepted")
        self.origin, self.token, self.deadline = origin.rstrip("/"), token, deadline
        self.http = httpx.AsyncClient(
            verify=ssl.create_default_context(cafile=ca_file),
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        )
        self.requests = 0

    async def call(
        self, method: str, path: str, body: dict | None = None, expected: tuple[int, ...] = (200,)
    ) -> tuple[int, dict]:
        self.requests += 1
        if self.requests > 250:
            raise QualificationError("Bounded request budget exceeded")
        budget = remaining(self.deadline, 20)
        data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode() if body is not None else None
        # The outer timeout bounds the whole response, including a slowly trickling
        # body. Per-socket read timeouts alone do not establish a total deadline.
        async with asyncio.timeout(budget):
            async with self.http.stream(
                method,
                self.origin + path,
                content=data,
                timeout=budget,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    "X-Correlation-ID": "p06-live-qualification",
                },
            ) as response:
                status = response.status_code
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    remaining(self.deadline, 20)
                    raw.extend(chunk)
                    if len(raw) > 1048576:
                        raise QualificationError("Response exceeded one MiB")
        value = json.loads(raw)
        if status not in expected:
            code = (
                value.get("error", {}).get("code", "unclassified")
                if isinstance(value, dict)
                else "non_object"
            )
            raise QualificationError(
                f"Unexpected HTTP {status} ({code}); no write was automatically repeated"
            )
        if not isinstance(value, dict):
            raise QualificationError("Expected a JSON object")
        return status, value

    async def get(self, path: str) -> dict:
        return (await self.call("GET", path))[1]


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationError(message)


async def wait_state(api: Client, case_id: str, allowed: set[str], deadline: float) -> dict:
    terminal = {
        "COMPLETED",
        "APPROVAL_INVALIDATED",
        "RECONCILIATION_REQUIRED",
        "NEEDS_CLARIFICATION",
        "ESCALATED",
        "COMPENSATED",
        "FAILED",
        "EXPIRED",
        "REJECTED",
    }
    while time.monotonic() < deadline:
        case = await api.get(f"/api/v1/cases/{quote(case_id, safe='')}")
        if case["state"] in allowed:
            return case
        if case["state"] in terminal:
            raise QualificationError(f"Case reached {case['state']} before the expected state")
        await asyncio.sleep(remaining(deadline, 1))
    raise QualificationError(
        "Case state deadline exceeded; preserve its ID and inspect instead of resubmitting"
    )


async def collect_temporal(case_ids: list[str], output: Path, deadline: float) -> list[dict]:
    from temporalio.client import Client as TemporalClient
    from temporalio.client import WorkflowExecutionStatus

    client = await asyncio.wait_for(
        TemporalClient.connect(
            os.environ["P06_TEMPORAL_ADDRESS"], namespace=os.environ.get("P06_TEMPORAL_NAMESPACE", "default")
        ),
        timeout=remaining(deadline, 20),
    )
    evidence = []
    for case_id in case_ids:
        handle = client.get_workflow_handle(f"case-{case_id}")
        description = await handle.describe(rpc_timeout=timedelta(seconds=remaining(deadline, 10)))
        memo = await asyncio.wait_for(description.memo(), timeout=remaining(deadline, 10))
        ensure(description.workflow_type == "OrderExceptionWorkflow", "Unexpected Temporal workflow type")
        ensure(memo.get("case_id") == case_id, "Temporal memo did not bind the case ID")
        # DB terminal state can precede Temporal's final WorkflowExecutionCompleted event briefly.
        await asyncio.wait_for(handle.result(), timeout=remaining(deadline, 30))
        description = await handle.describe(rpc_timeout=timedelta(seconds=remaining(deadline, 10)))
        ensure(
            description.status == WorkflowExecutionStatus.COMPLETED,
            "Temporal workflow did not close normally",
        )
        history = await handle.fetch_history(rpc_timeout=timedelta(seconds=remaining(deadline, 10)))
        (output / f"temporal-{case_id}.json").write_text(history.to_json(), encoding="utf-8")
        attempts = [
            event.activity_task_started_event_attributes.attempt
            for event in history.events
            if event.HasField("activity_task_started_event_attributes")
        ]
        evidence.append(
            {
                "case_id": case_id,
                "workflow_id": description.id,
                "run_id": description.run_id,
                "workflow_type": description.workflow_type,
                "status": description.status.name,
                "maximum_observed_activity_attempt": max(attempts, default=0),
                "history_events": len(history.events),
            }
        )
    return evidence


async def main() -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-seconds", type=int, default=240)
    args = parser.parse_args()
    deadline = started + args.max_seconds
    required = [
        "P06_API_URL",
        "P06_REQUESTER_TOKEN",
        "P06_APPROVER_TOKEN",
        "P06_OPERATOR_TOKEN",
        "P06_MULE_DIRECT_URL",
        "P06_MULE_TOKEN",
        "P06_MULE_READER_URL",
        "P06_MULE_READER_TOKEN",
        "P06_FAULT_URL",
        "P06_FAULT_CONTROL_TOKEN",
        "P06_TEMPORAL_ADDRESS",
        "P06_TENANT",
        "P06_CUSTOMER_REFERENCE",
        "P06_ORDER_REFERENCE",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if not args.execute or os.getenv("P06_LIVE_SCOPE") != "synthetic_nonproduction" or missing:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "executed": False,
                    "missing_environment": missing,
                    "reason": "Requires --execute, P06_LIVE_SCOPE=synthetic_nonproduction, and pre-provisioned authorized fixtures.",
                }
            )
        )
        return 2
    ensure(30 <= args.max_seconds <= 600, "Runtime must be bounded between 30 and 600 seconds")
    ensure(
        not args.output.exists(),
        "Evidence output must be a new directory; existing evidence is never overwritten",
    )
    args.output.mkdir(parents=True)
    run_id = uuid4().hex
    report = {
        "schema_version": "1.0",
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "RUNNING",
        "case_ids": [],
        "submitted_requests": [],
        "checks": {},
        "qualification": "real_vendor_workflow",
        "project_acceptance": "requires_maintainer_review",
        "scope": "synthetic_nonproduction",
        "max_seconds": args.max_seconds,
    }
    report_path = args.output / "report.json"

    def save() -> None:
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    save()
    clients: list[Client] = []
    try:
        async with asyncio.timeout_at(deadline):
            try:
                report["git_commit"] = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True, timeout=remaining(deadline, 10)
                ).strip()
                report["worktree_dirty"] = bool(
                    subprocess.check_output(
                        ["git", "status", "--porcelain"], text=True, timeout=remaining(deadline, 10)
                    ).strip()
                )
            except (OSError, subprocess.CalledProcessError):
                report["git_commit"] = "unavailable"
            report["temporal_sdk_version"] = importlib.metadata.version("temporalio")
            report["command"] = (
                "uv run python integrations/vendor_validation/live_acceptance.py --execute --output <new-evidence-directory>"
            )
            ca = os.getenv("P06_CA_FILE")
            api = Client(os.environ["P06_API_URL"], os.environ["P06_REQUESTER_TOKEN"], deadline, ca)
            approver = Client(os.environ["P06_API_URL"], os.environ["P06_APPROVER_TOKEN"], deadline, ca)
            operator = Client(os.environ["P06_API_URL"], os.environ["P06_OPERATOR_TOKEN"], deadline, ca)
            mule = Client(os.environ["P06_MULE_DIRECT_URL"], os.environ["P06_MULE_TOKEN"], deadline, ca)
            reader = Client(
                os.environ["P06_MULE_READER_URL"], os.environ["P06_MULE_READER_TOKEN"], deadline, ca
            )
            faults = Client(os.environ["P06_FAULT_URL"], os.environ["P06_FAULT_CONTROL_TOKEN"], deadline, ca)
            clients = [api, approver, operator, mule, reader, faults]
            tenant = os.environ["P06_TENANT"]
            session = await api.get("/api/v1/session")
            approval_session = await approver.get("/api/v1/session")
            operator_session = await operator.get("/api/v1/session")
            ensure(session["profile"] == "salesforce", "API is not running the real salesforce profile")
            ensure(
                all(s["actor"]["tenant_id"] == tenant for s in (session, approval_session, operator_session)),
                "Configured actors belong to different tenants",
            )
            ensure(
                session["actor"]["actor_id"] != approval_session["actor"]["actor_id"],
                "Requester and approver must be distinct",
            )
            ensure(
                "approver" in approval_session["actor"]["roles"]
                and "operator" in operator_session["actor"]["roles"],
                "Missing actor roles",
            )
            capabilities = await mule.get("/v1/capabilities")
            read_capabilities = await reader.get("/v1/capabilities")
            ensure(
                capabilities.get("provider") == "salesforce" and capabilities.get("can_execute") is True,
                "Executor provider capabilities do not match",
            )
            ensure(
                read_capabilities.get("provider") == "salesforce"
                and read_capabilities.get("can_execute") is False,
                "Reader must be a separately provisioned Salesforce identity without execute permission",
            )
            ensure(
                capabilities.get("tenant_id") == tenant and read_capabilities.get("tenant_id") == tenant,
                "Vendor tenant binding mismatch",
            )
            ensure(
                (await faults.get("/__p06_faults/state"))["evidence"] is None,
                "Use a fresh one-shot fault proxy process",
            )
            report["capabilities"] = {"executor": capabilities, "reader": read_capabilities}

            # Ensure a real Temporal service can answer before creating the cases.
            async def temporal_probe():
                from temporalio.client import Client as TemporalClient

                connection = await asyncio.wait_for(
                    TemporalClient.connect(
                        os.environ["P06_TEMPORAL_ADDRESS"],
                        namespace=os.environ.get("P06_TEMPORAL_NAMESPACE", "default"),
                    ),
                    timeout=remaining(deadline, 20),
                )
                ensure(
                    await connection.service_client.check_health(
                        timeout=timedelta(seconds=remaining(deadline, 10))
                    ),
                    "Temporal health probe failed",
                )

            await temporal_probe()
            requested = date.today() + timedelta(days=10)
            case_request = {
                "schema_version": "1.0",
                "message_id": f"vendor-{run_id}-loss",
                "customer_reference": os.environ["P06_CUSTOMER_REFERENCE"],
                "order_reference": os.environ["P06_ORDER_REFERENCE"],
                "requested_date": requested.isoformat(),
                "message": "Synthetic qualification. No customer notification or commercial commitment.",
            }
            report["submitted_requests"].append(case_request)
            save()
            _, created = await api.call("POST", "/api/v1/cases", case_request, (202,))
            first_id = created["id"]
            report["case_ids"].append(first_id)
            save()
            first = await wait_state(api, first_id, {"AWAITING_APPROVAL"}, deadline)
            _, duplicate = await api.call("POST", "/api/v1/cases", case_request, (202,))
            ensure(duplicate["id"] == first_id, "Duplicate message created a second case")
            stale_request = dict(
                case_request,
                message_id=f"vendor-{run_id}-stale",
                requested_date=(requested + timedelta(days=1)).isoformat(),
            )
            report["submitted_requests"].append(stale_request)
            save()
            _, second_created = await api.call("POST", "/api/v1/cases", stale_request, (202,))
            second_id = second_created["id"]
            report["case_ids"].append(second_id)
            save()
            stale = await wait_state(api, second_id, {"AWAITING_APPROVAL"}, deadline)
            ensure(
                stale["plan"]["order"]["revision"] == first["plan"]["order"]["revision"],
                "The two plans did not observe the same CRM revision",
            )
            await faults.call("POST", "/__p06_faults/arm", {"effect_key": f"{first_id}:crm"})
            await approver.call(
                "POST",
                f"/api/v1/cases/{first_id}/approval",
                {"plan_hash": first["plan"]["hash"], "decision": "approve"},
                (202,),
            )
            completed = await wait_state(api, first_id, {"COMPLETED"}, deadline)
            fault = (await faults.get("/__p06_faults/state"))["evidence"]
            ensure(
                fault is not None and fault["fault"] == "real_mule_success_response_dropped",
                "Worker did not traverse the armed fault proxy",
            )
            original_request = fault["request"]
            ensure(
                original_request["effect_key"] == f"{first_id}:crm"
                and original_request["approved_plan_hash"] == first["plan"]["hash"],
                "Dropped response was not bound to the approved plan",
            )
            order_id = first["plan"]["order"]["order_id"]
            scope = urlencode({"tenant_id": tenant})
            observed_effect = await mule.get(
                f"/v1/effects/{quote(original_request['effect_key'], safe='')}?{scope}"
            )
            observed_order = await mule.get(f"/v1/orders/{quote(order_id, safe='')}?{scope}")
            ensure(
                observed_effect == fault["upstream_response"],
                "Reconciled effect differs from the dropped real response",
            )
            ensure(
                observed_effect.get("approved_plan_hash") == first["plan"]["hash"],
                "Salesforce receipt is not bound to the approved plan",
            )
            ensure(observed_order == observed_effect["after"], "CRM readback differs from effect after-state")
            ensure(
                observed_order["revision"] == first["plan"]["order"]["revision"] + 1,
                "The CRM revision did not advance exactly once",
            )
            _, replay = await mule.call("POST", f"/v1/orders/{order_id}/effects", original_request, (200,))
            ensure(
                replay.get("replayed") is True, "Real remote endpoint did not identify an immutable replay"
            )
            ensure(
                await mule.get(f"/v1/orders/{order_id}?{scope}") == observed_order, "Replay changed CRM state"
            )
            # The identical committed request is safe even if the reader is accidentally overprivileged.
            status, denied = await reader.call(
                "POST", f"/v1/orders/{order_id}/effects", original_request, (403,)
            )
            ensure(
                status == 403 and denied.get("error", {}).get("code") == "permission_denied",
                "Denial did not originate from Salesforce's execute authorization",
            )
            ensure(
                await mule.get(f"/v1/orders/{order_id}?{scope}") == observed_order,
                "Rights test changed the order",
            )
            await approver.call(
                "POST",
                f"/api/v1/cases/{second_id}/approval",
                {"plan_hash": stale["plan"]["hash"], "decision": "approve"},
                (202,),
            )
            invalidated = await wait_state(api, second_id, {"APPROVAL_INVALIDATED"}, deadline)
            status, _ = await mule.call(
                "GET", f"/v1/effects/{quote(second_id + ':crm', safe='')}?{scope}", expected=(404,)
            )
            ensure(status == 404, "Invalidated approval unexpectedly produced a CRM effect")
            _, reconciled = await operator.call("POST", f"/api/v1/cases/{first_id}/reconcile", {}, (200,))
            ensure(
                reconciled["reconciliation"]["matches"] is True,
                "Operator readback did not reconcile CRM and ERP",
            )
            report["cases"] = {"completed": completed, "invalidated": invalidated, "reconciled": reconciled}
            report["fault_evidence"] = fault
            report["provider_protocol"] = {
                "replayed": replay,
                "denial": denied,
                "observed_order": observed_order,
            }
            report["temporal"] = await collect_temporal(report["case_ids"], args.output, deadline)
            report["checks"] = {
                "actual_api_temporal_mule_salesforce_path": True,
                "duplicate_intake_same_case": True,
                "approved_stale_snapshot_invalidated": True,
                "salesforce_permission_denial": True,
                "real_response_dropped_after_commit": True,
                "crm_revision_advanced_once": True,
                "immutable_remote_replay_no_change": True,
                "crm_and_erp_readback_match": True,
            }
            report["status"] = "EXECUTED_CHECKS_PASSED"
            report["note"] = (
                "Provider protocol and the recorded business scenarios were exercised. Broader production readiness, human approval of release, worker crash, quotas, restore and all other acceptance gates require their own evidence."
            )
    except Exception as error:
        report["status"] = "FAILED_OR_BLOCKED"
        report["error_type"] = type(error).__name__
        report["deadline_exceeded"] = time.monotonic() >= deadline
        # Only our bounded messages are safe to include; upstream exceptions can contain credentials.
        report["reason"] = (
            str(error)
            if isinstance(error, QualificationError)
            else "Execution stopped; inspect retained case IDs and provider state before any retry."
        )
    finally:
        # Closing already-owned sockets does not submit a new provider operation.
        for client in clients:
            await client.http.aclose()
        report["duration_seconds"] = round(time.monotonic() - started, 3)
        report["finished_at"] = datetime.now(UTC).isoformat()
        save()
    print(
        json.dumps({"status": report["status"], "report": str(report_path), "case_ids": report["case_ids"]})
    )
    return 0 if report["status"] == "EXECUTED_CHECKS_PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
