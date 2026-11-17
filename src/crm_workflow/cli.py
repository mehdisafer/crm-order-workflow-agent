"""Bounded local operations. No command provisions provider accounts or paid resources."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path

from crm_workflow.config import Settings
from crm_workflow.demo import seed_demo
from crm_workflow.models import Actor, ApprovalRequest, OrderRequest, timestamp
from crm_workflow.store import Store


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_private(path: Path, content: str) -> None:
    """Create a secret file exclusively with private permissions, never following a preexisting link."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)


def init_demo():
    settings = Settings.from_env()
    if (
        settings.profile != "demo"
        or not settings.database_url.startswith("sqlite:///")
        or settings.database_url == "sqlite:///:memory:"
    ):
        raise SystemExit("init-demo requires profile=demo with a persistent local SQLite database")

    target = Path(".local")
    if target.is_symlink():
        raise SystemExit("Demo directory cannot be a symbolic link")
    target.mkdir(mode=0o700, exist_ok=True)
    files = [target / p for p in ("principals.json", "tokens.json", "demo.env")]
    if any(p.exists() or p.is_symlink() for p in files):
        raise SystemExit("Demo identities already exist; no credentials were overwritten")

    # Seed before issuing credentials: a database failure must not leave half-created identities.
    store = Store(settings.database_url)
    try:
        seed_demo(store)
    finally:
        store.close()

    tokens = {role: secrets.token_urlsafe(32) for role in ("requester", "approver", "operator")}
    principals = [
        {
            "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            "actor_id": role,
            "tenant_id": "demo-industrial",
            "roles": [role, "operator"] if role != "operator" else [role],
        }
        for role, token in tokens.items()
    ]
    write_private(files[0], json.dumps({"principals": principals}, indent=2, sort_keys=True) + "\n")
    write_private(files[1], json.dumps(tokens, indent=2, sort_keys=True) + "\n")
    write_private(
        files[2],
        "P06_WEBHOOK_SECRET="
        + secrets.token_urlsafe(32)
        + "\nP06_ERP_TOKEN="
        + secrets.token_urlsafe(32)
        + "\nP06_POSTGRES_PASSWORD="
        + secrets.token_urlsafe(32)
        + "\n",
    )
    print(
        "Created local identities and synthetic data. Tokens are in .local/tokens.json (never commit this file)."
    )


def export_contracts(destination: str):
    from crm_workflow.api import create_app
    from crm_workflow.erp import ReservationRequest
    from crm_workflow.models import (
        ActionPlan,
        ApprovalRequest,
        Availability,
        CaseEvent,
        CaseResponse,
        Customer,
        EffectEvidence,
        Order,
        OrderRequest,
    )

    target = Path(destination)
    for model in (
        OrderRequest,
        Customer,
        Order,
        Availability,
        ActionPlan,
        ApprovalRequest,
        ReservationRequest,
        CaseEvent,
        EffectEvidence,
        CaseResponse,
    ):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"urn:p06:v1:{model.__name__}"
        write_json(target / f"{model.__name__}.schema.json", schema)
    write_json(target / "openapi.json", create_app().openapi())


async def smoke(output: str):
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from crm_workflow.dispatcher import OutboxDispatcher
    from crm_workflow.runtime import build_runtime
    from crm_workflow.temporal_workflow import OrderExceptionWorkflow
    from crm_workflow.worker import CaseActivities

    with tempfile.TemporaryDirectory(prefix="p06-smoke-") as temporary:
        settings = Settings(
            database_url=f"sqlite:///{temporary}/workflow.db", temporal_task_queue="p06-smoke"
        )
        store = Store(settings.database_url)
        seed_demo(store)
        store.close()
        runtime = build_runtime(settings)
        try:
            async with await WorkflowEnvironment.start_local(dev_server_log_level="error") as env:
                activities = CaseActivities(runtime.service)
                dispatcher = OutboxDispatcher(runtime.store, env.client, settings)
                async with Worker(
                    env.client,
                    task_queue=settings.temporal_task_queue,
                    workflows=[OrderExceptionWorkflow],
                    activities=activities.registered(),
                ):
                    requester = Actor(
                        actor_id="smoke-requester", tenant_id="demo-industrial", roles=["requester"]
                    )
                    approver = Actor(
                        actor_id="smoke-approver", tenant_id="demo-industrial", roles=["approver"]
                    )
                    case = await runtime.service.create_case(
                        OrderRequest(
                            message_id="smoke-1",
                            customer_reference="CUST-001",
                            order_reference="ORD-1001",
                            requested_date=date.today() + timedelta(days=10),
                        ),
                        requester,
                    )
                    await dispatcher.dispatch_once()
                    for _ in range(150):
                        case = runtime.store.get_case(case["id"])
                        if case["state"] != "RECEIVED":
                            break
                        await asyncio.sleep(0.1)
                    if case["state"] != "AWAITING_APPROVAL":
                        raise RuntimeError(f"Smoke could not obtain proposal: {case['state']}")
                    await runtime.service.approve(
                        case["id"],
                        ApprovalRequest(plan_hash=case["plan"]["hash"], decision="approve"),
                        approver,
                    )
                    await dispatcher.dispatch_once()
                    await asyncio.wait_for(env.client.get_workflow_handle(f"case-{case['id']}").result(), 45)
                    await dispatcher.dispatch_once()
                    result = runtime.store.get_case(case["id"])
                    record = {
                        "executed_at": timestamp(),
                        "profile": "isolated-synthetic-with-real-temporal",
                        "vendor_validated": False,
                        "case": result,
                        "outbox": runtime.store.outbox_stats(),
                        "command": "uv run --locked python -m crm_workflow.cli smoke",
                    }
                    write_json(output, record)
                    if result["state"] != "COMPLETED" or not result["reconciliation"]["matches"]:
                        raise RuntimeError("Smoke reconciliation failed")
                    print(
                        json.dumps(
                            {
                                "state": result["state"],
                                "effects": len(result["effects"]),
                                "evidence": output,
                                "vendor_validated": False,
                            }
                        )
                    )
        finally:
            await runtime.close()


def backup(source: str, destination: str):
    """Online SQLite backup API; copying a live WAL database is not a valid backup."""
    destination_path = Path(destination)
    if destination_path.exists():
        raise SystemExit("Backup destination already exists; choose a new path")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{Path(source).resolve()}?mode=ro", uri=True) as origin:
        with sqlite3.connect(destination_path) as target:
            origin.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
    destination_path.chmod(0o600)


def restore_check(source: str, output: str):
    with tempfile.TemporaryDirectory(prefix="p06-restore-") as directory:
        restored = Path(directory) / "restored.db"
        backup(source, str(restored))
        with sqlite3.connect(restored) as db:
            counts = {
                table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                for table in ("cases", "effects", "case_events", "outbox")
            }
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            orphan_effects = db.execute(
                "SELECT COUNT(*) FROM effects e LEFT JOIN cases c ON c.id=e.case_id WHERE c.id IS NULL"
            ).fetchone()[0]
        if integrity != "ok" or orphan_effects:
            raise RuntimeError("Restored database failed integrity/relationship checks")
        write_json(
            output,
            {
                "executed_at": timestamp(),
                "engine": "sqlite",
                "source_sha256": hashlib.sha256(Path(source).read_bytes()).hexdigest(),
                "restored_counts": counts,
                "integrity": integrity,
                "orphan_effects": orphan_effects,
                "scope": "database restoration to an isolated path; provider state and Temporal history require separate recovery",
            },
        )
        print(json.dumps({"restoration": "verified", "counts": counts, "evidence": output}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-demo")
    commands.add_parser("migrate")
    seed = commands.add_parser("seed-demo")
    seed.add_argument("--count", type=int, default=3)
    contracts = commands.add_parser("export-contracts")
    contracts.add_argument("--destination", default="contracts/v1")
    smoke_parser = commands.add_parser("smoke")
    smoke_parser.add_argument("--output", default="evidence-local/smoke.json")
    backup_parser = commands.add_parser("backup")
    backup_parser.add_argument("source")
    backup_parser.add_argument("destination")
    restore = commands.add_parser("restore-check")
    restore.add_argument("source")
    restore.add_argument("--output", default="evidence-local/restore.json")
    replay = commands.add_parser("replay-outbox")
    replay.add_argument("event_id")
    args = parser.parse_args()
    if args.command == "init-demo":
        init_demo()
    elif args.command in {"migrate", "seed-demo", "replay-outbox"}:
        settings = Settings.from_env()
        store = Store(settings.database_url)
        try:
            if args.command == "seed-demo":
                if settings.profile != "demo" or not 1 <= args.count <= 1000:
                    raise SystemExit("Seeding requires demo profile and 1..1000 synthetic orders per tenant")
                seed_demo(store, count=args.count)
            elif args.command == "replay-outbox":
                store.replay_outbox(args.event_id)
        finally:
            store.close()
        print(f"{args.command} complete")
    elif args.command == "export-contracts":
        export_contracts(args.destination)
    elif args.command == "smoke":
        asyncio.run(smoke(args.output))
    elif args.command == "backup":
        backup(args.source, args.destination)
    elif args.command == "restore-check":
        restore_check(args.source, args.output)


if __name__ == "__main__":
    main()
