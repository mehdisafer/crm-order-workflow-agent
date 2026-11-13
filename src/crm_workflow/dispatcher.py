"""At-least-once outbox delivery with stable Temporal identities."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from crm_workflow.temporal_workflow import CaseWorkflowInput, OrderExceptionWorkflow

logger = logging.getLogger(__name__)


class OutboxDispatcher:
    """One delivery attempt per poll; the store owns durable backoff and the DLQ."""

    def __init__(self, store: Any, client: Client, settings: Any) -> None:
        self.store = store
        self.client = client
        self.settings = settings
        self.rpc_timeout = timedelta(seconds=10)

    async def _describe_matching(self, case_id: str) -> Any:
        description = await self.client.get_workflow_handle(f"case-{case_id}").describe(
            rpc_timeout=self.rpc_timeout
        )
        memo = await description.memo()
        if (
            description.workflow_type != "OrderExceptionWorkflow"
            or memo.get("case_id") != case_id
            or memo.get("contract_version") != 1
        ):
            raise ValueError("WORKFLOW_ID_CONFLICT")
        return description

    async def _start(self, case_id: str) -> None:
        settings = self.settings
        params = CaseWorkflowInput(
            case_id=case_id,
            activity_timeout_seconds=settings.activity_timeout_seconds,
            activity_total_timeout_seconds=settings.activity_total_timeout_seconds,
            retry_max_attempts=settings.retry_max_attempts,
        )
        # A total workflow timeout leaves room for all bounded activity stages after
        # the human deadline, including failure reporting and guarded compensation.
        execution_seconds = settings.approval_ttl_seconds + 12 * settings.activity_total_timeout_seconds
        try:
            await self.client.start_workflow(
                OrderExceptionWorkflow.run,
                params,
                id=f"case-{case_id}",
                task_queue=settings.temporal_task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                execution_timeout=timedelta(seconds=execution_seconds),
                task_timeout=timedelta(seconds=10),
                memo={"case_id": case_id, "contract_version": 1},
                rpc_timeout=self.rpc_timeout,
            )
        except WorkflowAlreadyStartedError:
            # Reconcile the exact workflow rather than interpreting any collision as success.
            await self._describe_matching(case_id)

    async def _decision(self, case_id: str) -> None:
        description = await self._describe_matching(case_id)
        closed = {
            WorkflowExecutionStatus.COMPLETED,
            WorkflowExecutionStatus.CANCELED,
            WorkflowExecutionStatus.FAILED,
            WorkflowExecutionStatus.TERMINATED,
            WorkflowExecutionStatus.TIMED_OUT,
        }
        if description.status in closed:
            return
        try:
            await self.client.get_workflow_handle(f"case-{case_id}", run_id=description.run_id).signal(
                "decision", rpc_timeout=self.rpc_timeout
            )
        except RPCError as exc:
            if exc.status not in {RPCStatusCode.NOT_FOUND, RPCStatusCode.FAILED_PRECONDITION}:
                raise
            description = await self._describe_matching(case_id)
            if description.status in closed:
                # A late duplicate signal cannot revive or mutate a completed workflow.
                return
            raise

    async def dispatch_once(self, *, limit: int = 50) -> dict[str, int]:
        result = {"delivered": 0, "failed": 0}
        for item in self.store.pending_outbox(limit=limit):
            try:
                if item["kind"] == "workflow.start":
                    await self._start(item["case_id"])
                elif item["kind"] == "workflow.decision":
                    await self._decision(item["case_id"])
                elif item["kind"] == "notification.result":
                    # Notification is a local audit sink. No client email/chat is sent.
                    logger.info("result_notification", extra={"case_id": item["case_id"]})
                else:
                    raise ValueError("UNKNOWN_OUTBOX_KIND")
                self.store.ack_outbox(item["id"])
                result["delivered"] += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # No raw exception body: upstream errors can contain personal data or tokens.
                self.store.fail_outbox(item["id"], type(exc).__name__, max_attempts=8)
                result["failed"] += 1
                logger.warning("outbox_delivery_failed", extra={"outbox_id": item["id"]})
        return result

    async def run(self, stop: asyncio.Event, *, poll_interval: float = 0.5) -> None:
        while not stop.is_set():
            await self.dispatch_once()
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll_interval)
            except TimeoutError:
                pass
