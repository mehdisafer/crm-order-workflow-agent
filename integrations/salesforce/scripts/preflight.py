#!/usr/bin/env python3
"""Read-only vendor capability check. No secrets or full schemas enter the report."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get(url: str, token: str) -> dict:
    if urlsplit(url).scheme != "https":
        raise ValueError("Vendor endpoints must use HTTPS")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.build_opener(NoRedirect).open(req, timeout=15) as response:
        return json.load(response)


def main() -> int:
    required = ("P06_SF_INSTANCE_URL", "P06_SF_ACCESS_TOKEN", "P06_MULE_URL", "P06_MULE_TOKEN", "P06_TENANT")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        print(json.dumps({"status": "BLOCKED", "missing_environment": missing}))
        return 2
    sf = os.environ["P06_SF_INSTANCE_URL"].rstrip("/")
    host = urlsplit(sf).hostname or ""
    if not host.endswith(".salesforce.com") or urlsplit(sf).path not in ("", "/"):
        raise ValueError("Use the authorized Salesforce My Domain HTTPS origin")
    expected = {
        "Account": ["P06_Tenant__c", "P06_Reference__c"],
        "User": ["P06_Tenant__c"],
        "P06_Order__c": [
            "Tenant__c",
            "Customer__c",
            "Requested_Date__c",
            "Revision__c",
            "Last_Effect_Key__c",
        ],
        "P06_Effect__c": ["Key__c", "Request_Hash__c", "Response_JSON__c"],
    }
    objects = {}
    for name, fields in expected.items():
        description = get(
            f"{sf}/services/data/v65.0/sobjects/{name}/describe", os.environ["P06_SF_ACCESS_TOKEN"]
        )
        observed = {field["name"]: field for field in description["fields"]}
        objects[name] = {
            "available": True,
            "missing_fields": sorted(set(fields) - observed.keys()),
            "queryable": description.get("queryable"),
            "createable": description.get("createable"),
            "updateable": description.get("updateable"),
            "required_fields_updateable": {
                field: observed.get(field, {}).get("updateable") for field in fields
            },
        }
    query = urlencode({"tenant_id": os.environ["P06_TENANT"]})
    capabilities = get(
        f"{os.environ['P06_MULE_URL'].rstrip('/')}/v1/capabilities?{query}", os.environ["P06_MULE_TOKEN"]
    )
    ready = (
        all(not value["missing_fields"] for value in objects.values())
        and capabilities.get("provider") == "salesforce"
        and capabilities.get("tenant_id") == os.environ["P06_TENANT"]
        and capabilities.get("order_object") == "P06_Order__c"
    )
    print(
        json.dumps(
            {
                "status": "CAPABILITIES_OBSERVED" if ready else "BLOCKED",
                "checked_at": datetime.now(UTC).isoformat(),
                "objects": objects,
                "mule_salesforce_capabilities": capabilities,
                "acceptance": "NOT_EXECUTED",
                "mule_jvm_retry_properties": "NOT_OBSERVED",
                "note": "Read-only capability discovery does not prove a permitted or denied mutation.",
            },
            indent=2,
        )
    )
    return 0 if ready else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as error:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "http_status": error.code,
                    "reason": "Vendor read failed; response body intentionally omitted.",
                }
            )
        )
        sys.exit(2)
    except (ValueError, OSError) as error:
        print(json.dumps({"status": "BLOCKED", "reason": type(error).__name__}))
        sys.exit(2)
