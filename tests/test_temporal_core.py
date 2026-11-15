"""Real Temporal + persistent business core, including a process crash after write.

All CRM and ERP data here are the repository's original synthetic reference
systems. No assertion in this module is Salesforce/MuleSoft tenant evidence.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from crm_workflow.config import Settings
from crm_workflow.demo import crm_effects, reservations, seed_demo
from crm_workflow.dispatcher import OutboxDispatcher
from crm_workflow.models import Actor, ApprovalRequest, OrderRequest
from crm_workflow.runtime import build_runtime
from crm_workflow.store import Store
from crm_workflow.temporal_workflow import OrderExceptionWorkflow
from crm_workflow.worker import CaseActivities

pytestmark = [pytest.mark.temporal, pytest.mark.asyncio]
REQUESTER = Actor(actor_id="requester", tenant_id="demo-industrial", roles=["requester"])
APPROVER = Actor(actor_id="approver", tenant_id="demo-industrial", roles=["approver"])


def settings_for(url, address, queue):
    return Settings(
        database_url=url,
        temporal_address=address,
        temporal_task_queue=queue,
        approval_ttl_seconds=120,
        activity_timeout_seconds=5,
        activity_total_timeout_seconds=30,
        request_timeout_seconds=0.2,
        retry_max_attempts=3,
    )


async def start_server(database, *, port=None):
    if os.environ.get("RUN_TEMPORAL_TESTS") != "1":
        pytest.skip("Set RUN_TEMPORAL_TESTS=1 to execute the real Temporal server profile")
    options = {
        "dev_server_database_filename": str(database),
        "dev_server_startup_timeout": timedelta(seconds=20),
    }
    if port:
        options["port"] = port
    if os.environ.get("TEMPORAL_CLI_PATH"):
        options["dev_server_existing_path"] = os.environ["TEMPORAL_CLI_PATH"]
    return await asyncio.wait_for(WorkflowEnvironment.start_local(**options), timeout=60)


def initialise(database):
    url = f"sqlite:///{database}"
    store = Store(url)
    seed_demo(store)
    store.close()
    return url


async def create_case(runtime):
    request = OrderRequest(
        message_id=f"temporal-{uuid.uuid4()}",
        customer_reference="CUST-001",
        order_reference="ORD-1001",
        requested_date=date.today() + timedelta(days=10),
    )
    return await runtime.service.create_case(request, REQUESTER)


async def await_case_state(runtime, case_id, expected, *, timeout=15):
    async def poll():
        while True:
            value = runtime.store.get_case(case_id)
            if value["state"] == expected:
                return value
            await asyncio.sleep(0.03)

    return await asyncio.wait_for(poll(), timeout=timeout)


def worker_for(env, runtime):
    return Worker(
        env.client,
        task_queue=runtime.settings.temporal_task_queue,
        workflows=[OrderExceptionWorkflow],
        activities=CaseActivities(runtime.service).registered(),
        max_concurrent_activities=4,
        max_cached_workflows=0,
        graceful_shutdown_timeout=timedelta(seconds=2),
    )


def assert_one_effect_per_system(runtime, case_id):
    with runtime.store.engine.connect() as db:
        assert db.scalar(select(func.count()).select_from(crm_effects)) == 1
        assert db.scalar(select(func.count()).select_from(reservations)) == 1
    final = runtime.store.get_case(case_id)
    assert final["state"] == "COMPLETED"
    assert final["reconciliation"]["matches"] is True
    assert final["reconciliation"]["crm_order"]["revision"] == 2
    assert len(final["effects"]) == 2
    assert {effect["status"] for effect in final["effects"]} == {"APPLIED"}


async def crash_worker(url, address, queue, marker):
    """Process-only fault injection: die after remote commit and before its ACK."""
    runtime = build_runtime(settings_for(url, address, queue))
    original = runtime.service.crm

    class CrashAfterRemoteCommit:
        def __getattr__(self, name):
            return getattr(original, name)

        async def apply(self, order_id, payload, correlation_id):
            await original.apply(order_id, payload, correlation_id)
            Path(marker).write_text(
                json.dumps({"remote_committed": True, "effect_key": payload["effect_key"]})
            )
            # Deliberate hard process exit; no application finally blocks or ACK can run.
            os._exit(86)

    runtime.service.crm = CrashAfterRemoteCommit()
    client = await Client.connect(address)
    async with Worker(
        client,
        task_queue=queue,
        workflows=[OrderExceptionWorkflow],
        activities=CaseActivities(runtime.service).registered(),
    ):
        await asyncio.Event().wait()


async def test_process_crash_after_crm_commit_recovers_without_duplicate(tmp_path):
    env = await start_server(tmp_path / "temporal.db")
    url = initialise(tmp_path / "business.db")
    queue = f"p06-core-{uuid.uuid4()}"
    address = env.client.service_client.config.target_host
    runtime = build_runtime(settings_for(url, address, queue))
    marker = tmp_path / "remote-committed.json"
    process = None
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--crash-worker",
                url,
                address,
                queue,
                str(marker),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        case = await create_case(runtime)
        dispatcher = OutboxDispatcher(runtime.store, env.client, runtime.settings)
        assert (await dispatcher.dispatch_once())["failed"] == 0
        waiting = await await_case_state(runtime, case["id"], "AWAITING_APPROVAL")
        await runtime.service.approve(
            case["id"], ApprovalRequest(plan_hash=waiting["plan"]["hash"], decision="approve"), APPROVER
        )
        assert (await dispatcher.dispatch_once())["failed"] == 0

        async def crashed():
            while process.poll() is None:
                await asyncio.sleep(0.03)

        await asyncio.wait_for(crashed(), timeout=15)
        assert process.returncode == 86
        assert json.loads(marker.read_text())["remote_committed"] is True
        assert runtime.store.get_case(case["id"])["state"] == "APPROVED"
        assert runtime.store.effect(f"{case['id']}:crm")["status"] == "UNKNOWN"
        handle = env.client.get_workflow_handle(f"case-{case['id']}")
        async with worker_for(env, runtime):
            # Cover activity recovery windows and stale-worker task routing.
            # This harness deadline is not an application latency target.
            recovery_deadline = 2 * runtime.settings.activity_total_timeout_seconds + 10
            assert (await asyncio.wait_for(handle.result(), timeout=recovery_deadline))[
                "state"
            ] == "COMPLETED"
        assert_one_effect_per_system(runtime, case["id"])
        assert runtime.store.effect(f"{case['id']}:crm")["attempts"] == 1
        await Replayer(workflows=[OrderExceptionWorkflow]).replay_workflow(await handle.fetch_history())
    finally:
        if process and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        await runtime.close()
        await env.shutdown()


async def test_server_and_worker_restart_recover_outbox_and_approval(tmp_path):
    history_db = tmp_path / "temporal-persistent.db"
    env = await start_server(history_db)
    url = initialise(tmp_path / "business-persistent.db")
    queue = f"p06-core-{uuid.uuid4()}"
    address = env.client.service_client.config.target_host
    port = int(address.rsplit(":", 1)[1])
    runtime = build_runtime(settings_for(url, address, queue))
    try:
        case = await create_case(runtime)
        dispatcher = OutboxDispatcher(runtime.store, env.client, runtime.settings)
        async with worker_for(env, runtime):
            # Simulate a lost successful start ACK: the outbox row stays pending.
            await dispatcher._start(case["id"])
            waiting = await await_case_state(runtime, case["id"], "AWAITING_APPROVAL")
        await env.shutdown()
        await runtime.close()

        runtime = build_runtime(settings_for(url, address, queue))
        await runtime.service.approve(
            case["id"], ApprovalRequest(plan_hash=waiting["plan"]["hash"], decision="approve"), APPROVER
        )
        env = await start_server(history_db, port=port)
        dispatcher = OutboxDispatcher(runtime.store, env.client, runtime.settings)
        async with worker_for(env, runtime):
            delivery = await dispatcher.dispatch_once()
            assert delivery == {"delivered": 2, "failed": 0}
            handle = env.client.get_workflow_handle(f"case-{case['id']}")
            assert (await asyncio.wait_for(handle.result(), timeout=15))["state"] == "COMPLETED"
        assert_one_effect_per_system(runtime, case["id"])
        assert (await dispatcher.dispatch_once())["failed"] == 0
        assert runtime.store.outbox_stats() == {"pending": 0, "dead": 0}
        await Replayer(workflows=[OrderExceptionWorkflow]).replay_workflow(await handle.fetch_history())
    finally:
        await runtime.close()
        await env.shutdown()


if __name__ == "__main__" and len(sys.argv) == 6 and sys.argv[1] == "--crash-worker":
    asyncio.run(crash_worker(*sys.argv[2:]))
