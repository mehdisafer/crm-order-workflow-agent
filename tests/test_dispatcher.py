"""Control-plane contract tests; fake clients do not prove remote permissions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from crm_workflow.dispatcher import OutboxDispatcher


@pytest.fixture
def delivery():
    store = SimpleNamespace(pending_outbox=Mock(return_value=[]), ack_outbox=Mock(), fail_outbox=Mock())
    handle = SimpleNamespace(describe=AsyncMock(), signal=AsyncMock())
    handle.describe.return_value = SimpleNamespace(
        workflow_type="OrderExceptionWorkflow",
        memo=AsyncMock(return_value={"case_id": "case-1", "contract_version": 1}),
        status=WorkflowExecutionStatus.RUNNING,
        run_id="run-1",
    )
    client = SimpleNamespace(start_workflow=AsyncMock(), get_workflow_handle=Mock(return_value=handle))
    settings = SimpleNamespace(
        activity_timeout_seconds=30,
        activity_total_timeout_seconds=120,
        retry_max_attempts=3,
        approval_ttl_seconds=900,
        temporal_task_queue="p06-test",
    )
    return OutboxDispatcher(store, client, settings), store, client, handle


async def test_start_has_stable_identity_and_no_workflow_retry(delivery):
    dispatcher, store, client, _ = delivery
    store.pending_outbox.return_value = [{"id": 11, "kind": "workflow.start", "case_id": "case-1"}]
    assert await dispatcher.dispatch_once() == {"delivered": 1, "failed": 0}
    args = client.start_workflow.call_args.kwargs
    assert args["id"] == "case-case-1"
    assert args["id_reuse_policy"] == WorkflowIDReusePolicy.REJECT_DUPLICATE
    assert "retry_policy" not in args
    assert args["memo"] == {"case_id": "case-1", "contract_version": 1}
    store.ack_outbox.assert_called_once_with(11)


async def test_lost_start_ack_reconciles_matching_existing_workflow(delivery):
    dispatcher, store, client, handle = delivery
    store.pending_outbox.return_value = [{"id": 12, "kind": "workflow.start", "case_id": "case-1"}]
    client.start_workflow.side_effect = WorkflowAlreadyStartedError("case-case-1", "OrderExceptionWorkflow")
    assert await dispatcher.dispatch_once() == {"delivered": 1, "failed": 0}
    handle.describe.assert_awaited_once()
    store.ack_outbox.assert_called_once_with(12)


async def test_id_collision_is_not_falsely_acknowledged(delivery):
    dispatcher, store, client, handle = delivery
    store.pending_outbox.return_value = [{"id": 12, "kind": "workflow.start", "case_id": "case-1"}]
    client.start_workflow.side_effect = WorkflowAlreadyStartedError("case-case-1", "OtherWorkflow")
    handle.describe.return_value.workflow_type = "OtherWorkflow"
    assert await dispatcher.dispatch_once() == {"delivered": 0, "failed": 1}
    store.ack_outbox.assert_not_called()
    store.fail_outbox.assert_called_once_with(12, "ValueError", max_attempts=8)


async def test_signal_payload_cannot_grant_approval(delivery):
    dispatcher, store, client, handle = delivery
    store.pending_outbox.return_value = [
        {"id": 13, "kind": "workflow.decision", "case_id": "case-1", "payload": {"approved": True}}
    ]
    assert await dispatcher.dispatch_once() == {"delivered": 1, "failed": 0}
    handle.signal.assert_awaited_once_with("decision", rpc_timeout=dispatcher.rpc_timeout)
    client.get_workflow_handle.assert_called_with("case-case-1", run_id="run-1")


async def test_late_decision_does_not_restart_completed_workflow(delivery):
    dispatcher, store, client, handle = delivery
    store.pending_outbox.return_value = [{"id": 14, "kind": "workflow.decision", "case_id": "case-1"}]
    handle.describe.return_value.status = WorkflowExecutionStatus.COMPLETED
    assert await dispatcher.dispatch_once() == {"delivered": 1, "failed": 0}
    handle.signal.assert_not_awaited()
    client.start_workflow.assert_not_awaited()


async def test_missing_workflow_keeps_decision_in_outbox(delivery):
    dispatcher, store, _, handle = delivery
    store.pending_outbox.return_value = [{"id": 15, "kind": "workflow.decision", "case_id": "case-1"}]
    handle.describe.side_effect = RPCError("not found", RPCStatusCode.NOT_FOUND, b"")
    assert await dispatcher.dispatch_once() == {"delivered": 0, "failed": 1}
    store.ack_outbox.assert_not_called()
    store.fail_outbox.assert_called_once_with(15, "RPCError", max_attempts=8)


async def test_notification_is_local_and_unknown_commands_fail_closed(delivery):
    dispatcher, store, client, handle = delivery
    store.pending_outbox.return_value = [
        {"id": 16, "kind": "notification.result", "case_id": "case-1"},
        {"id": 17, "kind": "arbitrary.execute", "case_id": "case-1"},
    ]
    assert await dispatcher.dispatch_once() == {"delivered": 1, "failed": 1}
    client.start_workflow.assert_not_awaited()
    handle.signal.assert_not_awaited()
    store.ack_outbox.assert_called_once_with(16)
    store.fail_outbox.assert_called_once_with(17, "ValueError", max_attempts=8)


def test_concurrent_ack_wins_over_late_dispatch_failure(tmp_path):
    from sqlalchemy import select

    from crm_workflow.store import Store, outbox

    store = Store(f"sqlite:///{tmp_path / 'outbox.db'}")
    try:
        case = store.create_case({"message_id": "one"}, {"actor_id": "requester", "tenant_id": "tenant"})
        entry = store.pending_outbox()[0]
        store.ack_outbox(entry["id"])
        store.fail_outbox(entry["id"], "late upstream timeout", max_attempts=1)
        with store.engine.connect() as db:
            saved = db.execute(select(outbox).where(outbox.c.case_id == case["id"])).mappings().one()
        assert saved["delivered_at"] is not None
        assert saved["dead"] == 0
        assert saved["attempts"] == 0
    finally:
        store.close()


def test_observed_effect_cannot_be_downgraded_by_overlapping_attempt(tmp_path):
    from crm_workflow.errors import DomainError
    from crm_workflow.store import Store

    store = Store(f"sqlite:///{tmp_path / 'effects.db'}")
    try:
        case = store.create_case({"message_id": "one"}, {"actor_id": "requester", "tenant_id": "tenant"})
        store.prepare_effect("key", case["id"], "crm", "change_delivery_date", {"scope": "approved"})
        store.effect_attempt("key", 3)
        store.record_effect("key", {"revision": 1}, {"revision": 2})
        with pytest.raises(DomainError, match="overlapping attempt"):
            store.effect_attempt("key", 3)
        assert store.effect("key")["status"] == "APPLIED"
        assert store.effect("key")["attempts"] == 1
    finally:
        store.close()


def test_concurrent_slot_release_preserves_shared_failure_counter(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import select

    from crm_workflow.store import Store, systems

    store = Store(f"sqlite:///{tmp_path / 'admission.db'}")
    try:
        keys = [store.acquire_slot("crm", 8, 60) for _ in range(8)]

        def release(key):
            store.release_slot(key, "crm", failed=True, threshold=100, reset=1)

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(release, keys))
        with store.engine.connect() as db:
            value = db.execute(select(systems).where(systems.c.name == "crm")).mappings().one()
        assert value["failures"] == 8
        assert value["version"] == 17
    finally:
        store.close()

def test_replaced_lease_cannot_mutate_circuit_or_release_new_owner(tmp_path):
    import time

    from sqlalchemy import select, update

    from crm_workflow.errors import TransientError
    from crm_workflow.store import Store, leases, systems

    url = f"sqlite:///{tmp_path / 'stale-release.db'}"
    first = Store(url)
    second = Store(url, initialize=False)
    try:
        stale = first.acquire_slot("crm", 1, 60)
        with first.engine.begin() as db:
            db.execute(
                update(leases).where(leases.c.id == stale).values(expires_at=time.time() - 1)
            )
        active = second.acquire_slot("crm", 1, 60)
        with first.engine.connect() as db:
            snapshot = dict(db.execute(select(systems).where(systems.c.name == "crm")).mappings().one())
            other_system = dict(db.execute(select(systems).where(systems.c.name == "erp")).mappings().one())

        # Releasing a CRM lease through the ERP system is not a valid circuit event.
        first.release_slot(active, "erp", failed=True, threshold=1, reset=45)
        with first.engine.connect() as db:
            current = db.execute(select(systems).where(systems.c.name == "erp")).mappings().one()
            assert dict(current) == other_system
            assert db.scalar(select(leases.c.id).where(leases.c.id == active)) == active

        # A late failure for a discarded lease must not open the new worker's circuit.
        first.release_slot(stale, "crm", failed=True, threshold=1, reset=45, retry_after=40)
        with first.engine.connect() as db:
            row = db.execute(select(systems).where(systems.c.name == "crm")).mappings().one()
            assert dict(row) == snapshot
            assert db.scalar(select(leases.c.id).where(leases.c.id == active)) == active
        with pytest.raises(TransientError, match="concurrency limit"):
            first.acquire_slot("crm", 1, 60)

        # Only the live lease records its own failure.
        second.release_slot(active, "crm", failed=True, threshold=1, reset=45)
        with second.engine.connect() as db:
            failed = dict(db.execute(select(systems).where(systems.c.name == "crm")).mappings().one())
        assert failed["failures"] == 1
        assert failed["open_until"] > time.time()

        # Duplicate successes from either old worker must not reset the new circuit.
        first.release_slot(stale, "crm", failed=False, threshold=1, reset=45)
        second.release_slot(active, "crm", failed=False, threshold=1, reset=45)
        with first.engine.connect() as db:
            assert dict(db.execute(select(systems).where(systems.c.name == "crm")).mappings().one()) == failed
        with pytest.raises(TransientError, match="circuit is open"):
            second.acquire_slot("crm", 1, 60)
    finally:
        second.close()
        first.close()


def test_expired_unclaimed_lease_is_retired_without_circuit_mutation(tmp_path):
    import time

    from sqlalchemy import select, update

    from crm_workflow.store import Store, leases, systems

    store = Store(f"sqlite:///{tmp_path / 'expired-lease.db'}")
    try:
        stale = store.acquire_slot("erp", 1, 60)
        with store.engine.begin() as db:
            db.execute(update(leases).where(leases.c.id == stale).values(expires_at=time.time() - 1))
        with store.engine.connect() as db:
            before = dict(db.execute(select(systems).where(systems.c.name == "erp")).mappings().one())
        store.release_slot(stale, "erp", failed=True, threshold=1, reset=30)
        with store.engine.connect() as db:
            assert db.scalar(select(leases.c.id).where(leases.c.id == stale)) is None
            assert dict(db.execute(select(systems).where(systems.c.name == "erp")).mappings().one()) == before
        fresh = store.acquire_slot("erp", 1, 60)
        store.release_slot(fresh, "erp", failed=False, threshold=1, reset=30)
    finally:
        store.close()
