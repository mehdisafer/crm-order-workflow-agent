"""Real Temporal server tests with explicitly synthetic business activities.

Set RUN_TEMPORAL_TESTS=1 to execute. A requested but unavailable server is a
failure, never a silently skipped integration. These tests prove orchestration,
replay and worker restart, not Salesforce/MuleSoft tenant acceptance.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from crm_workflow.errors import DomainError, TransientError, UnknownOutcome
from crm_workflow.temporal_workflow import CaseWorkflowInput, OrderExceptionWorkflow
from crm_workflow.worker import CaseActivities

pytestmark = [pytest.mark.temporal, pytest.mark.asyncio(loop_scope="module")]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def temporal_env(tmp_path_factory):
    if os.environ.get("RUN_TEMPORAL_TESTS") != "1":
        pytest.skip("Set RUN_TEMPORAL_TESTS=1 to execute the real Temporal server profile")
    database = tmp_path_factory.mktemp("temporal") / "history.sqlite"
    options: dict[str, Any] = {
        "dev_server_database_filename": str(database),
        "dev_server_startup_timeout": timedelta(seconds=20),
    }
    if os.environ.get("TEMPORAL_CLI_PATH"):
        options["dev_server_existing_path"] = os.environ["TEMPORAL_CLI_PATH"]
    env = await asyncio.wait_for(WorkflowEnvironment.start_local(**options), timeout=60)
    try:
        yield env
    finally:
        await env.shutdown()


class SyntheticService:
    """A deterministic fault fixture, not a substitute vendor adapter."""

    def __init__(self, *, state="AWAITING_APPROVAL", expires_in=20):
        self.current = {
            "id": str(uuid.uuid4()),
            "state": state,
            "reason": None,
            "plan": {"expires_at": (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat()},
            "crm_note": "UNTRUSTED-CRM-NOTE-MUST-NOT-ENTER-HISTORY",
        }
        self.calls: list[str] = []
        self.crm_writes = 0
        self.erp_writes = 0
        self.crm_lost_response = False
        self.reserve_error: Exception | None = None
        self.concurrent_human_edit = False
        self.failures_left = 0

    def value(self):
        return dict(self.current)

    async def prepare(self, case_id):
        assert case_id == self.current["id"]
        self.calls.append("prepare")
        return self.value()

    async def execute_crm(self, case_id):
        self.calls.append("execute_crm")
        if self.current["state"] == "CRM_APPLIED":
            # Simulate reading the durable remote effect before replaying a write.
            return self.value()
        if self.current["state"] != "APPROVED":
            raise DomainError("NOT_APPROVED", "An untrusted signal is not an approval")
        if self.failures_left:
            self.failures_left -= 1
            raise TransientError("upstream token must never be copied", retry_after=0.01)
        self.crm_writes += 1
        self.current["state"] = "CRM_APPLIED"
        if self.crm_lost_response:
            self.crm_lost_response = False
            raise UnknownOutcome("remote secret response lost", retry_after=0.01)
        return self.value()

    async def reserve_stock(self, case_id):
        self.calls.append("reserve_stock")
        if self.reserve_error:
            raise self.reserve_error
        self.erp_writes += 1
        self.current["state"] = "STOCK_RESERVED"
        return self.value()

    async def verify(self, case_id):
        self.calls.append("verify")
        self.current["state"] = "COMPLETED"
        return self.value()

    async def compensate(self, case_id, reason):
        self.calls.append("compensate")
        self.current["state"] = "RECONCILIATION_REQUIRED" if self.concurrent_human_edit else "COMPENSATED"
        self.current["reason"] = reason
        return self.value()

    async def fail(self, case_id, reason):
        self.calls.append("fail")
        self.current["state"] = "RECONCILIATION_REQUIRED" if self.crm_writes else "FAILED"
        self.current["reason"] = reason
        return self.value()

    async def expire(self, case_id):
        self.calls.append("expire")
        if self.current["state"] == "AWAITING_APPROVAL":
            self.current["state"] = "EXPIRED"
        return self.value()


def make_worker(env, queue, service):
    return Worker(
        env.client,
        task_queue=queue,
        workflows=[OrderExceptionWorkflow],
        activities=CaseActivities(service).registered(),
        max_concurrent_activities=4,
        max_cached_workflows=0,
        graceful_shutdown_timeout=timedelta(seconds=2),
    )


def params(service):
    return CaseWorkflowInput(
        case_id=service.current["id"],
        activity_timeout_seconds=5,
        activity_total_timeout_seconds=10,
        retry_max_attempts=3,
    )


async def start(env, queue, service):
    return await env.client.start_workflow(
        OrderExceptionWorkflow.run,
        params(service),
        id=f"case-{service.current['id']}",
        task_queue=queue,
        execution_timeout=timedelta(seconds=60),
    )


async def await_state(handle, expected, *, timeout=10):
    async def poll():
        while await handle.query("state") != expected:
            await asyncio.sleep(0.02)

    await asyncio.wait_for(poll(), timeout=timeout)


async def test_approval_is_database_authority_and_history_is_minimised(temporal_env):
    service = SyntheticService()
    queue = f"p06-{uuid.uuid4()}"
    async with make_worker(temporal_env, queue, service):
        handle = await start(temporal_env, queue, service)
        await await_state(handle, "AWAITING_APPROVAL")
        await handle.signal("decision")
        await asyncio.sleep(0.1)
        assert service.crm_writes == 0
        assert await handle.query("state") == "AWAITING_APPROVAL"
        service.current["state"] = "APPROVED"
        await handle.signal("decision")
        await handle.signal("decision")
        result = await asyncio.wait_for(handle.result(), timeout=10)
    assert result["state"] == "COMPLETED"
    assert service.crm_writes == 1
    assert service.erp_writes == 1
    history = await handle.fetch_history()
    assert "UNTRUSTED-CRM-NOTE" not in history.to_json()
    await Replayer(workflows=[OrderExceptionWorkflow]).replay_workflow(history)


async def test_expired_approval_cannot_mutate(temporal_env):
    service = SyntheticService(expires_in=0.15)
    queue = f"p06-{uuid.uuid4()}"
    async with make_worker(temporal_env, queue, service):
        handle = await start(temporal_env, queue, service)
        result = await asyncio.wait_for(handle.result(), timeout=10)
    assert result["state"] == "EXPIRED"
    assert service.crm_writes == service.erp_writes == 0


async def test_lost_remote_response_retries_activity_and_reconciles_once(temporal_env):
    service = SyntheticService(state="APPROVED")
    service.crm_lost_response = True
    queue = f"p06-{uuid.uuid4()}"
    async with make_worker(temporal_env, queue, service):
        handle = await start(temporal_env, queue, service)
        result = await asyncio.wait_for(handle.result(), timeout=10)
    assert result["state"] == "COMPLETED"
    assert service.calls.count("execute_crm") == 2
    assert service.crm_writes == service.erp_writes == 1
    history = await handle.fetch_history()
    assert "remote secret" not in history.to_json()
    await Replayer(workflows=[OrderExceptionWorkflow]).replay_workflow(history)


@pytest.mark.parametrize("human_edit,expected", [(False, "COMPENSATED"), (True, "RECONCILIATION_REQUIRED")])
async def test_stock_refusal_uses_guarded_compensation(temporal_env, human_edit, expected):
    service = SyntheticService(state="APPROVED")
    service.reserve_error = DomainError("STOCK_CHANGED", "Remote confidential details")
    service.concurrent_human_edit = human_edit
    queue = f"p06-{uuid.uuid4()}"
    async with make_worker(temporal_env, queue, service):
        handle = await start(temporal_env, queue, service)
        result = await asyncio.wait_for(handle.result(), timeout=10)
    assert result["state"] == expected
    assert service.calls.count("reserve_stock") == 1
    assert service.calls.count("compensate") == 1
    assert service.crm_writes == 1
    assert service.erp_writes == 0
    assert "Remote confidential details" not in (await handle.fetch_history()).to_json()


async def test_retry_budget_exhaustion_is_visible(temporal_env):
    service = SyntheticService(state="APPROVED")
    service.failures_left = 10
    queue = f"p06-{uuid.uuid4()}"
    async with make_worker(temporal_env, queue, service):
        handle = await start(temporal_env, queue, service)
        result = await asyncio.wait_for(handle.result(), timeout=10)
    assert result["state"] == "FAILED"
    assert service.calls.count("execute_crm") == 3
    assert service.crm_writes == 0
    assert service.calls.count("fail") == 1


async def test_worker_restart_recovers_durable_approval_wait(temporal_env):
    service = SyntheticService(expires_in=30)
    queue = f"p06-{uuid.uuid4()}"
    async with make_worker(temporal_env, queue, service):
        handle = await start(temporal_env, queue, service)
        await await_state(handle, "AWAITING_APPROVAL")
    # No worker is running when the approval signal is accepted by the server.
    service.current["state"] = "APPROVED"
    await handle.signal("decision")
    async with make_worker(temporal_env, queue, service):
        result = await asyncio.wait_for(handle.result(), timeout=10)
    assert result["state"] == "COMPLETED"
    assert service.crm_writes == service.erp_writes == 1
    await Replayer(workflows=[OrderExceptionWorkflow]).replay_workflow(await handle.fetch_history())


async def test_cancellation_records_visible_case_outcome(temporal_env):
    service = SyntheticService(expires_in=30)
    queue = f"p06-{uuid.uuid4()}"
    async with make_worker(temporal_env, queue, service):
        handle = await start(temporal_env, queue, service)
        await await_state(handle, "AWAITING_APPROVAL")
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), timeout=10)
    assert service.current["state"] == "FAILED"
    assert service.current["reason"] == "WORKFLOW_CANCELLED"
    assert service.crm_writes == 0
