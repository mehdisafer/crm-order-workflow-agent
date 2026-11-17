"""Deterministic saga orchestration. Business authority stays in CaseService."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError


@dataclass(frozen=True)
class CaseWorkflowInput:
    """Non-secret, versioned execution limits recorded in workflow history."""

    case_id: str
    contract_version: int = 1
    activity_timeout_seconds: int = 30
    activity_total_timeout_seconds: int = 120
    retry_max_attempts: int = 3


def failure_code(error: BaseException) -> str:
    """Keep credentials and upstream response bodies out of workflow history."""
    cause = error
    for _ in range(5):
        nested = getattr(cause, "cause", None)
        if not nested:
            break
        cause = nested
    if isinstance(cause, ApplicationError) and cause.type:
        return cause.type[:100]
    return type(cause).__name__


@workflow.defn(name="OrderExceptionWorkflow")
class OrderExceptionWorkflow:
    """CRM change -> ERP reservation -> readback, with guarded compensation."""

    def __init__(self) -> None:
        self._decision_received = False
        self._state = "RECEIVED"
        self._input: CaseWorkflowInput | None = None

    @workflow.signal(name="decision")
    def decision(self) -> None:
        # A signal never grants approval. The next activity reloads the durable decision.
        self._decision_received = True

    @workflow.query(name="state")
    def state(self) -> str:
        return self._state

    async def _call(self, operation: str, *extra: str) -> dict[str, Any]:
        assert self._input is not None
        result = await workflow.execute_activity(
            f"case.{operation}",
            args=[self._input.case_id, *extra],
            result_type=dict,
            start_to_close_timeout=timedelta(seconds=self._input.activity_timeout_seconds),
            schedule_to_close_timeout=timedelta(seconds=self._input.activity_total_timeout_seconds),
            heartbeat_timeout=timedelta(seconds=min(10, self._input.activity_timeout_seconds)),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                backoff_coefficient=2,
                maximum_interval=timedelta(seconds=30),
                maximum_attempts=self._input.retry_max_attempts,
            ),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        self._state = result["state"]
        return result

    async def _expire_or_continue(self) -> dict[str, Any]:
        current = await self._call("expire")
        if current["state"] == "AWAITING_APPROVAL":
            # A premature timer or clock skew cannot end the workflow while approval is valid.
            # Avoid repeated immediate expiry activities if Temporal is ahead of store time.
            await workflow.sleep(timedelta(seconds=1))
        return current

    async def _await_decision(self, current: dict[str, Any]) -> dict[str, Any]:
        while current["state"] == "AWAITING_APPROVAL":
            raw_deadline = (current.get("plan") or {}).get("expires_at")
            if not raw_deadline:
                return await self._call("fail", "MISSING_APPROVAL_DEADLINE")
            deadline = datetime.fromisoformat(raw_deadline.replace("Z", "+00:00"))
            if deadline.tzinfo is None:
                return await self._call("fail", "INVALID_APPROVAL_DEADLINE")
            remaining = deadline.astimezone(UTC) - workflow.now()
            if remaining <= timedelta(0):
                current = await self._expire_or_continue()
                continue
            try:
                await workflow.wait_condition(lambda: self._decision_received, timeout=remaining)
            except TimeoutError:
                # The store deadline remains authoritative in an expiry/approval race.
                current = await self._expire_or_continue()
                continue
            self._decision_received = False
            current = await self._call("prepare")
        return current

    @workflow.run
    async def run(self, params: CaseWorkflowInput) -> dict[str, Any]:
        self._input = params
        if (
            params.contract_version != 1
            or not 1 <= params.retry_max_attempts <= 10
            or not 1 <= params.activity_timeout_seconds <= params.activity_total_timeout_seconds <= 3600
        ):
            raise ApplicationError(
                "Invalid execution limits", type="InvalidWorkflowInput", non_retryable=True
            )
        try:
            current = await self._call("prepare")
            current = await self._await_decision(current)
            if current["state"] == "APPROVED":
                current = await self._call("execute_crm")
            if current["state"] == "CRM_APPLIED":
                try:
                    current = await self._call("reserve_stock")
                except ActivityError as exc:
                    # The service reconciles an unknown reservation before compensating.
                    current = await self._call("compensate", f"RESERVATION_{failure_code(exc)}")
            if current["state"] == "STOCK_RESERVED":
                current = await self._call("verify")
            return current
        except asyncio.CancelledError:
            # Cancellation is not a rollback. Preserve potentially applied effects visibly.
            await asyncio.shield(self._call("fail", "WORKFLOW_CANCELLED"))
            raise
        except ActivityError as exc:
            return await self._call("fail", f"ACTIVITY_{failure_code(exc)}")
