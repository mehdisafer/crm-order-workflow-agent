#!/usr/bin/env python3
"""Observe only the relevant JVM properties of an explicitly selected Mule PID.

The complete jcmd output stays in memory and is never printed or saved because
other system properties can contain secrets. This is a runtime property check,
not an HTTP connector or Salesforce behavior test.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", required=True, type=int)
    args = parser.parse_args()
    if args.pid <= 0:
        parser.error("The explicitly selected runtime PID must be positive")
    jcmd = shutil.which("jcmd")
    if not jcmd:
        print(json.dumps({"status": "BLOCKED", "reason": "jcmd is unavailable"}))
        return 2
    try:
        result = subprocess.run(
            [jcmd, str(args.pid), "VM.system_properties"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        print(json.dumps({"status": "BLOCKED", "reason": "Cannot inspect the selected JVM"}))
        return 2
    if result.returncode or len(result.stdout) > 1048576:
        print(
            json.dumps(
                {"status": "BLOCKED", "reason": "Selected JVM did not return bounded system properties"}
            )
        )
        return 2
    expected = {
        "mule.http.client.maxRetries": "0",
        "mule.http.client.retryOnAllMethods": "false",
        "java.specification.version": "17",
    }
    properties = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and (key in expected or key == "P06_RUNTIME_CONFIG" or key == "mule.home"):
            properties[key] = value
    observed = {key: properties.get(key) for key in expected}
    checks = {key: observed[key] == value for key, value in expected.items()}
    checks["mule_runtime_identified"] = bool(properties.get("mule.home"))
    checks["external_configuration_matches"] = bool(os.getenv("P06_RUNTIME_CONFIG")) and (
        properties.get("P06_RUNTIME_CONFIG") == os.environ["P06_RUNTIME_CONFIG"]
    )
    passed = all(checks.values())
    print(
        json.dumps(
            {
                "status": "RUNTIME_PROPERTIES_OBSERVED" if passed else "BLOCKED",
                "checked_at": datetime.now(UTC).isoformat(),
                "pid": args.pid,
                "source": "running_jvm_system_properties",
                "observed": observed,
                "checks": checks,
                "connector_retry_behavior": "NOT_EXECUTED",
                "provider_acceptance": "OPEN",
            },
            indent=2,
        )
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
