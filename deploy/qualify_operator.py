"""Run the actual browser, API, HTTP ERP and Temporal together on loopback.

This development-only qualification creates original synthetic data and fresh
local credentials in an ignored, private session directory. It makes no vendor
calls, exposes no external listener and does not alter existing local identities.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import shutil
import socket
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from temporalio.api.enums.v1 import EventType
from temporalio.api.workflowservice.v1 import GetSystemInfoRequest
from temporalio.testing import WorkflowEnvironment

from crm_workflow.demo import seed_demo
from crm_workflow.store import Store


def local_ports():
    sockets = [socket.socket(socket.AF_INET, socket.SOCK_STREAM) for _ in range(2)]
    try:
        for listener in sockets:
            listener.bind(("127.0.0.1", 0))
        return [listener.getsockname()[1] for listener in sockets]
    finally:
        for listener in sockets:
            listener.close()


async def qualify(args):
    root = Path(__file__).resolve().parents[1]
    local = root / ".local"
    local.mkdir(mode=0o700, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix="browser-session-", dir=local))
    session.chmod(0o700)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    modules = Path(args.modules).resolve()
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node is required for the locked development browser tools")
    api_port, erp_port = local_ports()
    api_url, erp_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{erp_port}"
    environment = {key: value for key, value in os.environ.items() if not key.startswith("P06_")}
    environment.update(
        {
            "P06_CONFIG": str(root / "config/demo.yaml"),
            "P06_PROFILE": "demo",
            "P06_PROPOSER": "rules",
            "P06_DATABASE_URL": f"sqlite:///{session / 'workflow.db'}",
            "P06_AUTH_FILE": str(session / ".local/principals.json"),
            "P06_ERP_URL": erp_url,
            "P06_WEBHOOK_TENANT_ID": "demo-industrial",
            "P06_TEMPORAL_TASK_QUEUE": "p06-browser-reference",
            "P06_ALLOW_EXTERNAL_LLM": "false",
        }
    )
    report = {
        "captured_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "profile": "demo",
        "provider_validation": False,
        "topology": "Browser, API, HTTP ERP, worker and real Temporal are children of one loopback-only orchestration command.",
        "crm": "Original synthetic CRM in the application SQLite database",
        "erp": "Authenticated HTTP ERP with a separate transactional SQLite database",
        "api_url": api_url,
        "erp_url": erp_url,
        "temporal_sdk_version": importlib.metadata.version("temporalio"),
        "browser_engine_requested": args.engine,
        "runtime_command": "python deploy/qualify_operator.py",
    }
    processes = []
    logs = []
    temporal = None
    secret_values = []
    try:
        initializer = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "crm_workflow.cli",
            "init-demo",
            cwd=session,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await initializer.communicate()
        if initializer.returncode != 0:
            raise RuntimeError("Fresh synthetic identity initialization failed")
        tokens_path = session / ".local/tokens.json"
        tokens = json.loads(tokens_path.read_text())
        secret_values.extend(tokens.values())
        for line in (session / ".local/demo.env").read_text().splitlines():
            key, value = line.split("=", 1)
            if key in {"P06_ERP_TOKEN", "P06_WEBHOOK_SECRET"}:
                environment[key] = value
                secret_values.append(value)
        erp_database = session / "erp.db"
        store = Store(f"sqlite:///{erp_database}")
        seed_demo(store)
        store.close()
        temporal = await asyncio.wait_for(
            WorkflowEnvironment.start_local(
                ip="127.0.0.1",
                ui=False,
                dev_server_database_filename=str(session / "temporal.db"),
                dev_server_log_level="error",
                dev_server_startup_timeout=timedelta(seconds=20),
            ),
            timeout=60,
        )
        environment["P06_TEMPORAL_ADDRESS"] = temporal.client.service_client.config.target_host
        report["temporal_address"] = environment["P06_TEMPORAL_ADDRESS"]
        info = await temporal.client.workflow_service.get_system_info(GetSystemInfoRequest())
        report["temporal_server_version"] = info.server_version
        commands = [
            (
                "erp",
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "crm_workflow.erp:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(erp_port),
                    "--no-access-log",
                ],
                {"P06_DATABASE_URL": f"sqlite:///{erp_database}"},
            ),
            (
                "api",
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "crm_workflow.api:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--no-access-log",
                ],
                {},
            ),
            ("worker", [sys.executable, "-m", "crm_workflow.worker"], {}),
        ]
        for name, command, overrides in commands:
            log = (session / f"{name}.log").open("wb")
            logs.append(log)
            child = await asyncio.create_subprocess_exec(
                *command,
                cwd=root,
                env=environment | overrides,
                stdout=log,
                stderr=log,
            )
            processes.append((name, child))
        async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
            for _ in range(100):
                if any(child.returncode is not None for _, child in processes):
                    raise RuntimeError("A service exited during startup; inspect the private session logs")
                try:
                    api = await client.get(
                        api_url + "/health/ready", headers={"Authorization": f"Bearer {tokens['operator']}"}
                    )
                    erp = await client.get(erp_url + "/health/live")
                    if api.status_code == erp.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.2)
            else:
                raise RuntimeError("Loopback API and HTTP ERP did not become ready")
            print(
                json.dumps({"status": "services_ready", "api_url": api_url, "engine": args.engine}),
                flush=True,
            )
            browser = await asyncio.create_subprocess_exec(
                node,
                str(root / "deploy/capture_operator.mjs"),
                "--url",
                api_url,
                "--modules",
                str(modules),
                "--engine",
                args.engine,
                "--exercise",
                "true",
                "--tokens",
                str(tokens_path),
                "--output",
                str(output),
                cwd=root,
                env=environment,
            )
            processes.append(("browser", browser))
            await asyncio.wait_for(browser.wait(), timeout=300)
            browser_report = json.loads((output / "operator-browser.json").read_text())
            report["browser_exit_code"] = browser.returncode
            report["browser_status"] = browser_report["status"]
            exercise = browser_report.get("exercise")
            if exercise:
                case_id = exercise["case_id"]
                response = await client.get(
                    api_url + f"/api/v1/cases/{case_id}",
                    headers={"Authorization": f"Bearer {tokens['operator']}"},
                )
                response.raise_for_status()
                case = response.json()
                handle = temporal.client.get_workflow_handle(f"case-{case_id}")
                result = await asyncio.wait_for(handle.result(), timeout=15)
                history = await handle.fetch_history()
                description = await handle.describe()
                activities = [
                    event.activity_task_scheduled_event_attributes.activity_type.name
                    for event in history.events
                    if event.HasField("activity_task_scheduled_event_attributes")
                ]
                erp_effect = next(effect for effect in case["effects"] if effect["system"] == "erp")
                receipt = await client.get(
                    erp_url + f"/v1/reservations/{erp_effect['effect_key']}",
                    params={"tenant_id": "demo-industrial"},
                    headers={"Authorization": f"Bearer {environment['P06_ERP_TOKEN']}"},
                )
                receipt.raise_for_status()
                reservation = receipt.json()
                assert result["state"] == case["state"] == "COMPLETED"
                assert case["reconciliation"]["matches"] is True
                assert set(activities) >= {
                    "case.prepare",
                    "case.execute_crm",
                    "case.reserve_stock",
                    "case.verify",
                }
                assert reservation["effect_key"] == erp_effect["effect_key"]
                report["backend_observation"] = {
                    "case_id": case_id,
                    "workflow_status": description.status.name,
                    "workflow_result_state": result["state"],
                    "history_events": len(history.events),
                    "history_event_counts": dict(
                        Counter(EventType.Name(event.event_type) for event in history.events)
                    ),
                    "scheduled_activity_types": activities,
                    "api_state": case["state"],
                    "api_readback_matches": case["reconciliation"]["matches"],
                    "erp_receipt_http_status": receipt.status_code,
                    "erp_receipt": reservation,
                }
            report["status"] = "passed" if browser.returncode == 0 and exercise else "failed"
    except Exception as error:
        summary = str(error)
        for value in secret_values:
            summary = summary.replace(value, "[REDACTED]")
        report.update(
            status="failed", failure_type=type(error).__name__, failure_summary=summary.split("\n")[0]
        )
    finally:
        for _, child in reversed(processes):
            if child.returncode is None:
                child.terminate()
        for _, child in reversed(processes):
            if child.returncode is None:
                try:
                    await asyncio.wait_for(child.wait(), timeout=20)
                except TimeoutError:
                    child.kill()
                    await child.wait()
        report["process_exit_codes"] = {name: child.returncode for name, child in processes}
        for log in logs:
            log.close()
        if temporal is not None:
            await temporal.shutdown()
        (output / "runtime.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "evidence": str(output), "private_session": str(session)}))
    return 0 if report["status"] == "passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("chromium", "firefox", "webkit"), default="chromium")
    parser.add_argument("--modules", default=".local/browser-tools/node_modules")
    parser.add_argument("--output", default="evidence-local/browser")
    raise SystemExit(asyncio.run(qualify(parser.parse_args())))


if __name__ == "__main__":
    main()
