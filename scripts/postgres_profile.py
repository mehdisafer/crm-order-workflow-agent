"""Exercise business invariants and logical restore on an isolated loopback PostgreSQL.

Run with: uv run --locked --with pgserver==0.1.4 python scripts/postgres_profile.py
The optional helper supplies test binaries only; it is not the deployment image.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import socket
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pgserver
import psycopg
from sqlalchemy import func, select, text

from crm_workflow.cli import write_json
from crm_workflow.config import Settings
from crm_workflow.demo import DemoCRM, DemoERP, crm_effects, reservations, seed_demo
from crm_workflow.models import Actor, ApprovalRequest, OrderRequest, timestamp
from crm_workflow.proposer import RulesProposer
from crm_workflow.service import CaseService
from crm_workflow.store import Store, cases, effects, events, outbox


async def qualify(uri, binaries, directory):
    store = Store(uri.replace("postgresql://", "postgresql+psycopg://"))
    seed_demo(store)
    requester = Actor(actor_id="pg-requester", tenant_id="demo-industrial", roles=["requester"])
    approver = Actor(actor_id="pg-approver", tenant_id="demo-industrial", roles=["approver", "operator"])
    service = CaseService(store, DemoCRM(store), DemoERP(store), RulesProposer(), Settings())
    request = OrderRequest(
        message_id="same-message",
        customer_reference="CUST-001",
        order_reference="ORD-1001",
        requested_date=date.today() + timedelta(days=10),
    )
    started = time.perf_counter()
    try:
        # Real threads, separate database connections, one tenant/message uniqueness constraint.
        with ThreadPoolExecutor(max_workers=8) as executor:
            duplicates = list(
                executor.map(
                    lambda _: store.create_case(request.model_dump(mode="json"), requester.model_dump()),
                    range(16),
                )
            )
        assert len({x["id"] for x in duplicates}) == 1
        case = await service.prepare(duplicates[0]["id"])
        case = await service.approve(
            case["id"], ApprovalRequest(plan_hash=case["plan"]["hash"], decision="approve"), approver
        )
        case = await service.execute_crm(case["id"])
        assert case["state"] == "CRM_APPLIED"
        case = await service.reserve_stock(case["id"])
        case = await service.verify(case["id"])
        assert case["state"] == "COMPLETED" and case["reconciliation"]["matches"]
        with store.engine.connect() as db:
            version = db.scalar(text("SELECT version()"))
            tables = [cases, effects, events, outbox, crm_effects, reservations]
            original_counts = {
                table.name: db.scalar(select(func.count()).select_from(table)) for table in tables
            }
        dump = Path(directory) / "workflow.dump"
        subprocess.run(
            [str(binaries / "pg_dump"), "--dbname", uri, "--format=custom", "--file", str(dump)],
            check=True,
            timeout=20,
            capture_output=True,
        )
        with psycopg.connect(uri, autocommit=True) as db:
            db.execute("CREATE DATABASE p06_restored")
        restored_uri = uri.rsplit("/", 1)[0] + "/p06_restored"
        restore_start = time.perf_counter()
        subprocess.run(
            [str(binaries / "pg_restore"), "--dbname", restored_uri, "--exit-on-error", str(dump)],
            check=True,
            timeout=20,
            capture_output=True,
        )
        restored = Store(restored_uri.replace("postgresql://", "postgresql+psycopg://"), initialize=False)
        try:
            with restored.engine.connect() as db:
                restored_counts = {
                    table.name: db.scalar(select(func.count()).select_from(table)) for table in tables
                }
            assert restored_counts == original_counts
            restored_service = CaseService(
                restored, DemoCRM(restored), DemoERP(restored), RulesProposer(), Settings()
            )
            observed = await restored_service.reconcile(case["id"], approver)
            assert observed["reconciliation"]["matches"]
        finally:
            restored.close()
        record = {
            "executed_at": timestamp(),
            "profile": "isolated-loopback-postgresql",
            "postgres_version": version,
            "helper": {"name": "pgserver", "version": importlib.metadata.version("pgserver")},
            "duplicate_deliveries": 16,
            "unique_cases": 1,
            "case_state": case["state"],
            "source_counts": original_counts,
            "restored_counts": restored_counts,
            "restored_reconciliation_matches": True,
            "logical_restore_seconds": time.perf_counter() - restore_start,
            "qualification_seconds": time.perf_counter() - started,
            "dump_bytes": dump.stat().st_size,
            "vendor_validated": False,
            "limits": "Helper PostgreSQL binary, not the pinned container version. Temporal history and provider state are not part of this logical dump.",
        }
        write_json("docs/evidence/postgres-restore.json", record)
        print(json.dumps(record))
    finally:
        store.close()


def main():
    # Public helper wrappers carry their binary path; do not change machine services.
    binaries = Path(pgserver.pg_ctl.__globals__["POSTGRES_BIN_PATH"])
    with tempfile.TemporaryDirectory(prefix="p06-postgres-") as directory:
        data = Path(directory) / "data"
        subprocess.run(
            [
                str(binaries / "initdb"),
                "-D",
                str(data),
                "-U",
                "p06",
                "-A",
                "trust",
                "--no-locale",
                "-E",
                "UTF8",
            ],
            check=True,
            capture_output=True,
            timeout=20,
        )
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with open(Path(directory) / "postgres.log", "wb") as log:
            process = subprocess.Popen(
                [
                    str(binaries / "postgres"),
                    "-D",
                    str(data),
                    "-h",
                    "127.0.0.1",
                    "-p",
                    str(port),
                    "-c",
                    "unix_socket_directories=",
                ],
                stdout=log,
                stderr=log,
            )
            uri = f"postgresql://p06@127.0.0.1:{port}/postgres"
            try:
                for _ in range(100):
                    try:
                        with psycopg.connect(uri, connect_timeout=1):
                            break
                    except psycopg.OperationalError:
                        if process.poll() is not None:
                            raise RuntimeError("Isolated PostgreSQL failed to start") from None
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Isolated PostgreSQL startup deadline exceeded")
                asyncio.run(qualify(uri, binaries, directory))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
