"""Temporal worker and durable outbox dispatcher entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.service import RetryConfig
from temporalio.worker import Worker

from crm_workflow.dispatcher import OutboxDispatcher
from crm_workflow.temporal_workflow import OrderExceptionWorkflow

logger = logging.getLogger(__name__)


class SafeJsonFormatter(logging.Formatter):
    """Allowlisted structured context; no exception payloads or arbitrary extras."""

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for field in ("case_id", "outbox_id", "operation", "attempt", "error_code"):
            if hasattr(record, field):
                data[field] = getattr(record, field)
        return json.dumps(data, ensure_ascii=True)


def workflow_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    """Minimise Temporal history: CRM notes, names and tokens are never returned."""
    result = {"id": value["id"], "state": value["state"], "reason": value.get("reason")}
    if value.get("plan"):
        result["plan"] = {"expires_at": value["plan"].get("expires_at")}
    return result


class CaseActivities:
    def __init__(self, service: Any) -> None:
        self.service = service

    async def _run(self, operation: str, case_id: str, *args: str) -> dict[str, Any]:
        from crm_workflow.errors import DomainError, TransientError

        async def heartbeat() -> None:
            while True:
                activity.heartbeat(operation)
                await asyncio.sleep(1)

        heartbeat_task = asyncio.create_task(heartbeat()) if activity.in_activity() else None
        context = {
            "case_id": case_id,
            "operation": operation,
            "attempt": activity.info().attempt if activity.in_activity() else 1,
        }
        logger.info("activity_started", extra=context)
        try:
            value = await getattr(self.service, operation)(case_id, *args)
            logger.info("activity_completed", extra=context)
            return workflow_snapshot(value)
        except TransientError as exc:
            delay = getattr(exc, "retry_after", None)
            logger.warning("activity_transient_failure", extra={**context, "error_code": type(exc).__name__})
            raise ApplicationError(
                "Transient upstream failure; consult the effect journal",
                type=getattr(exc, "code", type(exc).__name__),
                next_retry_delay=timedelta(seconds=max(0.0, float(delay))) if delay is not None else None,
            ) from None
        except DomainError as exc:
            logger.warning("activity_refused", extra={**context, "error_code": exc.code})
            raise ApplicationError(
                "Business operation refused; consult the case audit",
                type=getattr(exc, "code", type(exc).__name__),
                non_retryable=True,
            ) from None
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("activity_internal_failure", extra=context)
            # Programming/configuration errors are not blindly replayed against remote systems.
            raise ApplicationError(
                "Unexpected activity failure; operator investigation required",
                type="INTERNAL_ACTIVITY_ERROR",
                non_retryable=True,
            ) from None
        finally:
            if heartbeat_task:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)

    @activity.defn(name="case.prepare")
    async def prepare(self, case_id: str) -> dict[str, Any]:
        return await self._run("prepare", case_id)

    @activity.defn(name="case.execute_crm")
    async def execute_crm(self, case_id: str) -> dict[str, Any]:
        return await self._run("execute_crm", case_id)

    @activity.defn(name="case.reserve_stock")
    async def reserve_stock(self, case_id: str) -> dict[str, Any]:
        return await self._run("reserve_stock", case_id)

    @activity.defn(name="case.verify")
    async def verify(self, case_id: str) -> dict[str, Any]:
        return await self._run("verify", case_id)

    @activity.defn(name="case.compensate")
    async def compensate(self, case_id: str, reason: str) -> dict[str, Any]:
        return await self._run("compensate", case_id, reason)

    @activity.defn(name="case.fail")
    async def fail(self, case_id: str, reason: str) -> dict[str, Any]:
        return await self._run("fail", case_id, reason)

    @activity.defn(name="case.expire")
    async def expire(self, case_id: str) -> dict[str, Any]:
        return await self._run("expire", case_id)

    def registered(self) -> list[Any]:
        return [
            self.prepare,
            self.execute_crm,
            self.reserve_stock,
            self.verify,
            self.compensate,
            self.fail,
            self.expire,
        ]


async def serve() -> None:
    from crm_workflow.runtime import build_runtime

    runtime = build_runtime()
    settings = runtime.settings
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed_signals: list[signal.Signals] = []
    for name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(name, stop.set)
            installed_signals.append(name)
        except NotImplementedError:
            # Windows receives KeyboardInterrupt through asyncio.run instead.
            pass
    try:
        client = await Client.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
            # RPC retries are bounded control-plane retries. Business retry authority
            # remains the Activity retry policy plus the persisted request budget.
            retry_config=RetryConfig(max_retries=2, max_elapsed_time_millis=3000),
        )
        activities = CaseActivities(runtime.service)
        dispatcher = OutboxDispatcher(runtime.store, client, settings)
        async with Worker(
            client,
            task_queue=settings.temporal_task_queue,
            workflows=[OrderExceptionWorkflow],
            activities=activities.registered(),
            max_concurrent_activities=settings.worker_concurrency,
            max_concurrent_workflow_tasks=max(2, settings.worker_concurrency),
            max_activities_per_second=settings.temporal_activity_rate_limit,
            max_task_queue_activities_per_second=settings.temporal_activity_rate_limit,
            disable_eager_activity_execution=True,
            graceful_shutdown_timeout=timedelta(seconds=settings.activity_timeout_seconds + 5),
        ):
            task = asyncio.create_task(dispatcher.run(stop), name="outbox-dispatcher")
            waiter = asyncio.create_task(stop.wait(), name="worker-stop")
            try:
                done, _ = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
                if task in done:
                    task.result()  # Propagate dispatcher faults instead of leaving a silent worker.
            finally:
                stop.set()
                waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)
                await task
    finally:
        for name in installed_signals:
            loop.remove_signal_handler(name)
        await runtime.close()


def main() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(SafeJsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
