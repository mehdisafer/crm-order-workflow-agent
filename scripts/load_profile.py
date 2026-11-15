"""Bounded synthetic load through real Temporal; never loads Salesforce or MuleSoft."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import resource
import statistics
import sys
import tempfile
import time
from collections import Counter
from contextlib import AsyncExitStack
from datetime import date, timedelta
from pathlib import Path

from temporalio.testing import WorkflowEnvironment

from crm_workflow.cli import write_json
from crm_workflow.config import Settings
from crm_workflow.demo import seed_demo
from crm_workflow.dispatcher import OutboxDispatcher
from crm_workflow.models import Actor, ApprovalRequest, OrderRequest, timestamp
from crm_workflow.runtime import build_runtime
from crm_workflow.store import Store


def percentile(values, percentile_value):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percentile_value))]


async def run(args):
    # Thresholds are declared before execution and scoped to this small isolated test.
    criteria = {
        "completed_fraction": 1.0,
        "duplicate_effects": 0,
        "automatic_p95_seconds_max": 60,
        "case_deadline_seconds": 120,
        "provider_requests": 0,
    }
    with tempfile.TemporaryDirectory(prefix="p06-load-") as temporary:
        settings = Settings(
            database_url=f"sqlite:///{temporary}/load.db",
            temporal_task_queue="p06-load",
            worker_concurrency=args.concurrency,
            retry_max_attempts=8,
            max_case_api_calls=120,
            activity_total_timeout_seconds=120,
            approval_ttl_seconds=120,
        )
        initial = Store(settings.database_url)
        seed_demo(initial, count=args.cases)
        initial.close()
        async with AsyncExitStack() as stack:
            env = await stack.enter_async_context(
                await WorkflowEnvironment.start_local(dev_server_log_level="error")
            )
            processes = []
            worker_environment = {
                **os.environ,
                "P06_PROFILE": "demo",
                "P06_PROPOSER": "rules",
                "P06_ERP_URL": "",
                "P06_DATABASE_URL": settings.database_url,
                "P06_TEMPORAL_ADDRESS": env.client.service_client.config.target_host,
                "P06_TEMPORAL_TASK_QUEUE": settings.temporal_task_queue,
                "P06_WORKER_CONCURRENCY": str(args.concurrency),
                "P06_RETRY_MAX_ATTEMPTS": "8",
                "P06_MAX_CASE_API_CALLS": "120",
                "P06_APPROVAL_TTL_SECONDS": "120",
                "P06_ACTIVITY_TOTAL_TIMEOUT_SECONDS": "120",
            }

            async def stop_worker(process):
                if process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), 45)
                    except TimeoutError:
                        process.kill()
                        await process.wait()

            for number in range(args.workers):
                log = stack.enter_context(open(Path(temporary) / f"worker-{number}.log", "wb"))
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "crm_workflow.worker",
                    env=worker_environment,
                    stdout=log,
                    stderr=log,
                )
                processes.append(process)
                stack.push_async_callback(stop_worker, process)
            runtime = build_runtime(settings)
            stack.push_async_callback(runtime.close)
            dispatcher = OutboxDispatcher(runtime.store, env.client, settings)
            stop = asyncio.Event()
            dispatch_task = asyncio.create_task(dispatcher.run(stop, poll_interval=0.05))
            requester = Actor(actor_id="load-requester", tenant_id="demo-industrial", roles=["requester"])
            approver = Actor(actor_id="load-approver", tenant_id="demo-industrial", roles=["approver"])
            counters = {"active": 0, "peak_active": 0, "peak_outbox_pending": 0}
            started = time.perf_counter()
            cpu_start = resource.getrusage(resource.RUSAGE_SELF)

            async def one(index):
                begin = time.perf_counter()
                counters["active"] += 1
                counters["peak_active"] = max(counters["active"], counters["peak_active"])
                case = await runtime.service.create_case(
                    OrderRequest(
                        message_id=f"load-{index}",
                        customer_reference="CUST-001",
                        order_reference=f"ORD-{1001 + index}",
                        requested_date=date.today() + timedelta(days=10),
                    ),
                    requester,
                )
                deadline = time.monotonic() + criteria["case_deadline_seconds"]
                approval_wait = 0
                while time.monotonic() < deadline:
                    current = runtime.store.get_case(case["id"])
                    counters["peak_outbox_pending"] = max(
                        counters["peak_outbox_pending"], runtime.store.outbox_stats()["pending"]
                    )
                    if current["state"] == "AWAITING_APPROVAL":
                        wait_start = time.perf_counter()
                        await asyncio.sleep(args.approval_delay)
                        approval_wait = time.perf_counter() - wait_start
                        await runtime.service.approve(
                            case["id"],
                            ApprovalRequest(plan_hash=current["plan"]["hash"], decision="approve"),
                            approver,
                        )
                        break
                    if current["state"] not in {"RECEIVED", "AWAITING_APPROVAL"}:
                        break
                    await asyncio.sleep(0.1)
                try:
                    await asyncio.wait_for(
                        env.client.get_workflow_handle(f"case-{case['id']}").result(),
                        max(1, deadline - time.monotonic()),
                    )
                except Exception as exc:
                    await runtime.service.fail(case["id"], type(exc).__name__)
                final = runtime.store.get_case(case["id"])
                counters["active"] -= 1
                return {
                    "case_id": case["id"],
                    "state": final["state"],
                    "seconds": time.perf_counter() - begin,
                    "simulated_human_wait_seconds": approval_wait,
                    "api_calls": final["api_calls"],
                    "effect_count": len([x for x in final["effects"] if x["status"] == "APPLIED"]),
                    "write_attempts": sum(x["attempts"] for x in final["effects"]),
                    "transient_failures": sum(
                        e["event_type"] == "system.transient_failure" for e in final["events"]
                    ),
                }

            try:
                records = await asyncio.gather(*(one(index) for index in range(args.cases)))
                await dispatcher.dispatch_once()
            finally:
                stop.set()
                await dispatch_task
            elapsed = time.perf_counter() - started
            cpu_end = resource.getrusage(resource.RUSAGE_SELF)
            automatic = [x["seconds"] - x["simulated_human_wait_seconds"] for x in records]
            states = dict(Counter(x["state"] for x in records))
            duplicate_effects = sum(max(0, x["effect_count"] - 2) for x in records)
            passed = (
                states.get("COMPLETED", 0) == args.cases
                and duplicate_effects == 0
                and percentile(automatic, 0.95) <= criteria["automatic_p95_seconds_max"]
            )
            result = {
                "executed_at": timestamp(),
                "profile": "isolated-synthetic-real-temporal",
                "criteria_declared_before_run": criteria,
                "thresholds_met": passed,
                "parameters": vars(args),
                "states": states,
                "wall_seconds": elapsed,
                "completed_cases_per_second": states.get("COMPLETED", 0) / elapsed,
                "automatic_seconds": {
                    "p50": statistics.median(automatic),
                    "p95": percentile(automatic, 0.95),
                    "max": max(automatic),
                },
                "simulated_human_wait_seconds": sum(x["simulated_human_wait_seconds"] for x in records),
                "saturation": counters,
                "duplicate_effects": duplicate_effects,
                "transient_failures": sum(x["transient_failures"] for x in records),
                "resources": {
                    "python_peak_rss_kib": cpu_end.ru_maxrss,
                    "python_cpu_seconds": cpu_end.ru_utime
                    + cpu_end.ru_stime
                    - cpu_start.ru_utime
                    - cpu_start.ru_stime,
                    "temporal_process_resources": "not measured",
                },
                "cost": {
                    "provider_requests": 0,
                    "external_llm_tokens": 0,
                    "currency_cost": None,
                    "note": "Local compute cost is not metered; no currency amount is inferred",
                },
                "limits": "SQLite in one isolated host; separate worker processes; synthetic systems; not vendor scale evidence",
                "cases": records,
            }
            write_json(args.output, result)
            print(
                json.dumps(
                    {
                        k: result[k]
                        for k in (
                            "thresholds_met",
                            "states",
                            "wall_seconds",
                            "automatic_seconds",
                            "duplicate_effects",
                        )
                    }
                )
            )
            if not passed:
                raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, choices=range(1, 101), default=24)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--concurrency", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--approval-delay", type=float, default=0.05)
    parser.add_argument("--output", default="evidence-local/load.json")
    arguments = parser.parse_args()
    if not 0 <= arguments.approval_delay <= 5:
        parser.error("approval delay must be between 0 and 5 seconds")
    asyncio.run(run(arguments))
