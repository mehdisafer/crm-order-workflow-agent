"""Qualify the real n8n trigger against isolated, synthetic business services.

Install the official n8n version separately. This script does not install software,
create an external account, accept a licence, or modify the versioned workflow.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import secrets
import signal
import socket
import sys
import tempfile
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from temporalio.testing import WorkflowEnvironment

from crm_workflow.demo import seed_demo
from crm_workflow.store import Store

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "integrations/n8n/order-intake.workflow.json"


def free_port():
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        return stream.getsockname()[1]


def private_json(path, value):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream)


def clean_environment():
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith(("P06_", "N8N_", "EXECUTIONS_"))
    }
    # Preserve the executor's external proxy settings, but make every supported
    # proxy selector keep the explicitly local fixture traffic on loopback.
    for key in (
        "NO_PROXY",
        "no_proxy",
        "NPM_CONFIG_NO_PROXY",
        "npm_config_no_proxy",
        "NPM_CONFIG_NOPROXY",
        "npm_config_noproxy",
    ):
        environment[key] = "127.0.0.1,localhost,::1"
    return environment


async def qualify(args):
    source_bytes = SOURCE.read_bytes()
    source = json.loads(source_bytes)
    if source["active"] or any("credentials" in node for node in source["nodes"]):
        raise ValueError("The versioned export must remain inactive and credential-free")
    report = {
        "captured_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "target_version": "2.47.5",
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "scope": "real-local-n8n-with-original-synthetic-crm-and-http-erp",
        "salesforce_mulesoft_validation": False,
        "external_accounts_created": False,
        "licence_activation_requested": False,
        "maximum_run_seconds": args.timeout,
        "runtime_changes_to_imported_copy": [
            "bind two generated httpHeaderAuth credentials",
            "replace the fixed API URL with the isolated loopback API URL",
            "publish only the imported instance-local workflow",
        ],
        "commands": [],
        "checks": {},
    }
    started = time.monotonic()
    sensitive = []
    processes = []
    files = []
    temporal = None
    stage = "prepare"

    def redact(value):
        for secret in sensitive:
            value = value.replace(secret, "[REDACTED]")
        return value

    async def stop(process):
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                await process.wait()
                return
            try:
                await asyncio.wait_for(process.wait(), 15)
            except TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()

    async def command(arguments, environment, *, timeout=100):
        print(json.dumps({"stage": stage, "command": arguments[1]}), flush=True)
        process = await asyncio.create_subprocess_exec(
            *arguments,
            cwd=ROOT,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout)
        except asyncio.CancelledError:
            await stop(process)
            raise
        except TimeoutError:
            await stop(process)
            raise TimeoutError(f"Command exceeded {timeout}s: {arguments[1]}") from None
        result = {
            "command": [str(value) for value in arguments],
            "exit_code": process.returncode,
            "output": redact(output.decode(errors="replace")),
        }
        report["commands"].append(result)
        if process.returncode:
            raise RuntimeError(f"Command failed: {arguments[1]} (exit {process.returncode})")
        return result["output"]

    async def launch(name, arguments, environment, session):
        print(json.dumps({"stage": stage, "service": name}), flush=True)
        path = session / f"{name}.log"
        stream = path.open("w")
        files.append((name, path, stream))
        process = await asyncio.create_subprocess_exec(
            *arguments,
            cwd=ROOT,
            env=environment,
            stdout=stream,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        processes.append((name, process))
        return process

    async def wait_http(client, url, process, *, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.returncode is not None:
                raise RuntimeError(f"Service exited before readiness: {url}")
            try:
                result = await client.get(url)
                if result.status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.2)
        raise TimeoutError(f"Service readiness timed out: {url}")

    session_parent = ROOT / "evidence-local"
    session_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="n8n-session-", dir=session_parent) as directory:
        session = Path(directory)
        try:
            ports = {name: free_port() for name in ("api", "erp", "n8n", "runner")}
            urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
            tokens = {name: secrets.token_urlsafe(32) for name in ("requester", "approver", "operator")}
            inbound, erp_token, encryption_key = (secrets.token_urlsafe(32) for _ in range(3))
            sensitive.extend([*tokens.values(), inbound, erp_token, encryption_key])
            principals = {
                "principals": [
                    {
                        "token_sha256": hashlib.sha256(value.encode()).hexdigest(),
                        "actor_id": name,
                        "tenant_id": "demo-industrial",
                        "roles": [name],
                    }
                    for name, value in tokens.items()
                ]
            }
            private_json(session / "principals.json", principals)
            database_urls = {}
            for name in ("business", "erp"):
                database_urls[name] = f"sqlite:///{session / (name + '.db')}"
                store = Store(database_urls[name])
                seed_demo(store)
                store.close()

            environment = clean_environment()
            n8n_env = {
                **environment,
                "DB_TYPE": "sqlite",
                "N8N_USER_FOLDER": str(session / "n8n-home"),
                "N8N_ENCRYPTION_KEY": encryption_key,
                "N8N_HOST": "127.0.0.1",
                "N8N_LISTEN_ADDRESS": "127.0.0.1",
                "N8N_PORT": str(ports["n8n"]),
                "N8N_PROTOCOL": "http",
                "N8N_SECURE_COOKIE": "false",
                "N8N_DIAGNOSTICS_ENABLED": "false",
                "N8N_PERSONALIZATION_ENABLED": "false",
                "N8N_VERSION_NOTIFICATIONS_ENABLED": "false",
                "N8N_TEMPLATES_ENABLED": "false",
                "N8N_LICENSE_AUTO_RENEW_ENABLED": "false",
                "N8N_LICENSE_DETACH_FLOATING_ON_SHUTDOWN": "false",
                "N8N_PUBLIC_API_DISABLED": "true",
                "N8N_COMMUNITY_PACKAGES_ENABLED": "false",
                "N8N_RUNNERS_BROKER_PORT": str(ports["runner"]),
                "N8N_RUNNERS_BROKER_LISTEN_ADDRESS": "127.0.0.1",
                "N8N_RUNNERS_MAX_CONCURRENCY": "1",
                "N8N_RUNNERS_MAX_OLD_SPACE_SIZE": "256",
                "N8N_CONCURRENCY_PRODUCTION_LIMIT": "1",
                "N8N_GRACEFUL_SHUTDOWN_TIMEOUT": "10",
                "N8N_SSRF_PROTECTION_ENABLED": "true",
                "N8N_SSRF_BLOCKED_IP_RANGES": "0.0.0.0/0,::/0",
                "N8N_SSRF_ALLOWED_IP_RANGES": "127.0.0.1/32",
                "EXECUTIONS_DATA_SAVE_ON_ERROR": "none",
                "EXECUTIONS_DATA_SAVE_ON_SUCCESS": "none",
                "EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS": "false",
                "NODE_OPTIONS": "--max-old-space-size=1024",
                "UV_THREADPOOL_SIZE": "2",
            }
            binary = str(Path(args.n8n_binary).resolve())
            stage = "version"
            report["n8n_version"] = (await command([binary, "--version"], n8n_env)).strip()
            if report["n8n_version"] != "2.47.5":
                raise RuntimeError("The installed n8n version differs from the qualification target")
            report["node_version"] = (await command(["node", "--version"], environment)).strip()
            stage = "import-original-inactive-export"
            await command([binary, "import:workflow", f"--input={SOURCE}"], n8n_env)
            exported = session / "imported-workflow.json"
            await command([binary, "export:workflow", "--all", f"--output={exported}"], n8n_env)
            imported = json.loads(exported.read_text())
            if len(imported) != 1 or imported[0]["active"]:
                raise AssertionError("The original export did not import as exactly one inactive workflow")
            workflow_id = imported[0]["id"]
            report["checks"]["original_export_imported_inactive"] = True
            report["workflow_id"] = workflow_id

            stage = "bind-local-credentials"
            inbound_id, outbound_id = uuid.uuid4().hex, uuid.uuid4().hex
            credentials = [
                {
                    "id": inbound_id,
                    "name": "P06 isolated inbound",
                    "type": "httpHeaderAuth",
                    "data": {"name": "X-P06-Intake-Key", "value": inbound},
                },
                {
                    "id": outbound_id,
                    "name": "P06 isolated requester",
                    "type": "httpHeaderAuth",
                    "data": {"name": "Authorization", "value": f"Bearer {tokens['requester']}"},
                },
            ]
            credentials_file = session / "credentials.json"
            private_json(credentials_file, credentials)
            await command([binary, "import:credentials", f"--input={credentials_file}"], n8n_env)
            bound = copy.deepcopy(source)
            bound["id"] = workflow_id
            for node in bound["nodes"]:
                if node["type"] == "n8n-nodes-base.webhook":
                    node["credentials"] = {
                        "httpHeaderAuth": {"id": inbound_id, "name": credentials[0]["name"]}
                    }
                if node["type"] == "n8n-nodes-base.httpRequest":
                    node["parameters"]["url"] = urls["api"] + "/api/v1/cases"
                    node["credentials"] = {
                        "httpHeaderAuth": {"id": outbound_id, "name": credentials[1]["name"]}
                    }
            bound_file = session / "bound-workflow.json"
            private_json(bound_file, bound)
            await command([binary, "import:workflow", f"--input={bound_file}"], n8n_env)
            stage = "publish-isolated-copy"
            await command([binary, "publish:workflow", f"--id={workflow_id}"], n8n_env)

            stage = "start-business-services"
            temporal = await asyncio.wait_for(
                WorkflowEnvironment.start_local(
                    dev_server_database_filename=str(session / "temporal.db"),
                    dev_server_log_level="error",
                    dev_server_startup_timeout=timedelta(seconds=30),
                ),
                timeout=60,
            )
            app_env = {
                **environment,
                "P06_PROFILE": "demo",
                "P06_DATABASE_URL": database_urls["business"],
                "P06_AUTH_FILE": str(session / "principals.json"),
                "P06_ERP_URL": urls["erp"],
                "P06_ERP_TOKEN": erp_token,
                "P06_TEMPORAL_ADDRESS": temporal.client.service_client.config.target_host,
                "P06_TEMPORAL_TASK_QUEUE": f"n8n-qualification-{uuid.uuid4()}",
                "P06_WORKER_CONCURRENCY": "2",
                "P06_CRM_CONCURRENCY": "1",
                "P06_ERP_CONCURRENCY": "1",
                "P06_APPROVAL_TTL_SECONDS": "120",
                "P06_ACTIVITY_TIMEOUT_SECONDS": "20",
                "P06_ACTIVITY_TOTAL_TIMEOUT_SECONDS": "60",
                "P06_REQUEST_TIMEOUT_SECONDS": "2",
                "P06_PROPOSER": "rules",
            }
            erp_env = {**app_env, "P06_DATABASE_URL": database_urls["erp"]}
            async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
                for name, module, env in (
                    ("erp", "crm_workflow.erp:app", erp_env),
                    ("api", "crm_workflow.api:app", app_env),
                ):
                    process = await launch(
                        name,
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            module,
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(ports[name]),
                            "--no-access-log",
                        ],
                        env,
                        session,
                    )
                    await wait_http(client, urls[name] + "/health/live", process)
                await launch("worker", [sys.executable, "-m", "crm_workflow.worker"], app_env, session)
                stage = "start-n8n"
                n8n = await launch("n8n", [binary, "start"], n8n_env, session)
                await wait_http(client, urls["n8n"] + "/healthz/readiness", n8n)
                webhook = urls["n8n"] + "/webhook/p06-order-intake"
                body = {
                    "schema_version": "1.0",
                    "message_id": f"n8n-qualification-{uuid.uuid4()}",
                    "customer_reference": "CUST-001",
                    "order_reference": "ORD-1001",
                    "requested_date": (date.today() + timedelta(days=10)).isoformat(),
                }

                async def api(method, path, role="operator", *, expected=200, data=None):
                    result = await client.request(
                        method,
                        urls["api"] + path,
                        headers={"Authorization": f"Bearer {tokens[role]}"},
                        json=data,
                    )
                    if result.status_code != expected:
                        raise AssertionError(
                            f"{method} {path}: expected {expected}, received {result.status_code}"
                        )
                    return result.json()

                stage = "authenticate-trigger"
                registration_deadline = time.monotonic() + 35
                registration_responses = []
                while True:
                    missing = await client.post(webhook, json=body)
                    registration_responses.append(missing.status_code)
                    if missing.status_code != 404 or time.monotonic() >= registration_deadline:
                        break
                    await asyncio.sleep(0.5)
                report["checks"]["webhook_registration_probe_statuses"] = registration_responses
                report["checks"]["missing_inbound_credential_status"] = missing.status_code
                if missing.status_code not in {401, 403}:
                    report["trigger_error_response"] = redact(missing.text)
                    raise AssertionError(
                        f"Expected registered webhook auth refusal; received {missing.status_code}"
                    )
                wrong = await client.post(webhook, headers={"X-P06-Intake-Key": "invalid"}, json=body)
                report["checks"]["wrong_inbound_credential_status"] = wrong.status_code
                assert wrong.status_code in {401, 403}, f"Wrong credential returned {wrong.status_code}"
                assert not (await api("GET", "/api/v1/cases"))["items"]
                stage = "trigger-through-real-n8n"
                trigger_started = time.monotonic()
                response = await client.post(webhook, headers={"X-P06-Intake-Key": inbound}, json=body)
                report["checks"]["authenticated_trigger_status"] = response.status_code
                if response.status_code != 202:
                    report["trigger_error_response"] = redact(response.text)
                    raise AssertionError(
                        f"n8n did not return the durable receipt: HTTP {response.status_code}"
                    )
                case = response.json()
                assert case["request"]["message_id"] == body["message_id"]
                assert case["requester_id"] == "requester"
                duplicate = await client.post(webhook, headers={"X-P06-Intake-Key": inbound}, json=body)
                assert duplicate.status_code == 202 and duplicate.json()["id"] == case["id"]
                report["checks"]["duplicate_delivery_same_case"] = True
                case_path = f"/api/v1/cases/{case['id']}"

                async def wait_case(expected):
                    deadline = time.monotonic() + 80
                    while time.monotonic() < deadline:
                        value = await api("GET", case_path)
                        if value["state"] == expected:
                            return value
                        if value["state"] not in {
                            "RECEIVED",
                            "AWAITING_APPROVAL",
                            "APPROVED",
                            "CRM_APPLIED",
                            "STOCK_RESERVED",
                        }:
                            raise AssertionError(f"Unexpected case state: {value['state']}")
                        await asyncio.sleep(0.15)
                    raise TimeoutError(f"Case did not reach {expected}")

                stage = "independent-approval-and-readback"
                waiting = await wait_case("AWAITING_APPROVAL")
                decision = {"plan_hash": waiting["plan"]["hash"], "decision": "approve"}
                await api("POST", case_path + "/approval", "requester", expected=403, data=decision)
                await api("POST", case_path + "/approval", "approver", expected=202, data=decision)
                final = await wait_case("COMPLETED")
                assert final["approval"]["actor_id"] == "approver" != final["requester_id"]
                observed = await api("POST", case_path + "/reconcile", data={})
                assert observed["reconciliation"]["matches"] is True
                assert len(final["effects"]) == 2
                assert all(
                    effect["status"] == "APPLIED" and effect["attempts"] == 1 for effect in final["effects"]
                )
                assert len((await api("GET", "/api/v1/cases"))["items"]) == 1
                handle = temporal.client.get_workflow_handle(f"case-{final['id']}")
                workflow_result = await asyncio.wait_for(handle.result(), timeout=10)
                assert workflow_result["id"] == final["id"] and workflow_result["state"] == "COMPLETED"
                history = await handle.fetch_history()
                report["checks"].update(
                    requester_approval_status=403,
                    independent_approver=True,
                    remote_readback_matches=True,
                    one_case=True,
                )
                report["business_result"] = {
                    "case_id": final["id"],
                    "correlation_id": final["correlation_id"],
                    "message_id": body["message_id"],
                    "temporal_workflow_id": history.workflow_id,
                    "temporal_run_id": history.run_id,
                    "temporal_history_events": len(history.events),
                    "state": final["state"],
                    "effects": [
                        {key: item[key] for key in ("system", "status", "attempts")}
                        for item in final["effects"]
                    ],
                    "trigger_to_completion_seconds": time.monotonic() - trigger_started,
                    "human_wait_seconds": 0,
                    "approval_note": "Distinct generated approver identity used automatically by this fixture.",
                }
                report["status"] = "passed"
        except asyncio.CancelledError:
            report["status"] = "blocked"
            report["failure"] = {
                "stage": stage,
                "type": "CancelledError",
                "message": "Qualification cancelled or the overall deadline elapsed",
            }
            raise
        except Exception as error:
            report["status"] = (
                "blocked"
                if stage in {"version", "import-original-inactive-export", "start-n8n"}
                else "failed"
            )
            report["failure"] = {"stage": stage, "type": type(error).__name__, "message": redact(str(error))}
        finally:
            for _name, process in reversed(processes):
                await stop(process)
            if temporal:
                await temporal.shutdown()
            report["all_services_stopped"] = all(process.returncode is not None for _, process in processes)
            report["service_exit_codes"] = {name: process.returncode for name, process in processes}
            report["source_export_unchanged"] = SOURCE.read_bytes() == source_bytes
            report["duration_seconds"] = time.monotonic() - started
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            service_logs = []
            for name, path, stream in files:
                stream.close()
                service_logs.append(f"### {name}\n{redact(path.read_text())}\n")
            output.with_suffix(".log").write_text("\n".join(service_logs))
            output.write_text(redact(json.dumps(report, indent=2)) + "\n")
    print(json.dumps({"status": report["status"], "failure": report.get("failure"), "evidence": str(output)}))
    return 0 if report["status"] == "passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n8n-binary", default=".local/n8n-runtime/node_modules/.bin/n8n")
    parser.add_argument("--output", default="docs/evidence/n8n-qualification.json")
    parser.add_argument("--timeout", type=int, default=420)
    args = parser.parse_args()
    if not 60 <= args.timeout <= 600:
        parser.error("--timeout must be between 60 and 600 seconds")

    async def bounded_run():
        return await asyncio.wait_for(qualify(args), timeout=args.timeout)

    raise SystemExit(asyncio.run(bounded_run()))


if __name__ == "__main__":
    main()
