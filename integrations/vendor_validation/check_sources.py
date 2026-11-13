#!/usr/bin/env python3
"""Source packaging checks only: these cannot establish vendor runtime behavior."""

from __future__ import annotations

import ast
import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    integrations = ROOT / "integrations"
    xml_files = sorted((integrations / "salesforce").rglob("*.xml")) + sorted(
        (integrations / "mulesoft").rglob("*.xml")
    )
    for path in xml_files:
        ET.parse(path)
    json_files = (
        sorted((integrations / "salesforce").rglob("*.json"))
        + sorted((integrations / "mulesoft").rglob("*.json"))
        + sorted((integrations / "n8n").rglob("*.json"))
    )
    for path in json_files:
        json.loads(path.read_text())
    python_files = (
        sorted((integrations / "vendor_validation").glob("*.py"))
        + sorted((integrations / "salesforce/scripts").glob("*.py"))
        + sorted((integrations / "mulesoft/scripts").glob("*.py"))
    )
    for path in python_files:
        ast.parse(path.read_text(), filename=str(path))
    workflow = json.loads((integrations / "n8n/order-intake.workflow.json").read_text())
    assert workflow["active"] is False
    assert not workflow["pinData"]
    assert all("credentials" not in node for node in workflow["nodes"])
    assert all(node.get("retryOnFail") is not True for node in workflow["nodes"])
    assert workflow["settings"]["saveDataErrorExecution"] == "none"
    names = {node["name"] for node in workflow["nodes"]}
    for source, channels in workflow["connections"].items():
        assert source in names
        for outputs in channels.values():
            for group in outputs:
                for edge in group:
                    assert edge["node"] in names
    sf = integrations / "salesforce/force-app/main/default"
    for metadata in (sf / "classes").glob("*.cls-meta.xml"):
        assert metadata.with_name(metadata.name.removesuffix("-meta.xml")).exists()
    for metadata in (sf / "triggers").glob("*.trigger-meta.xml"):
        assert metadata.with_name(metadata.name.removesuffix("-meta.xml")).exists()
    ns = {"m": "http://soap.sforce.com/2006/04/metadata"}
    for permission in (sf / "permissionsets").glob("*.xml"):
        for node in ET.parse(permission).findall("m:fieldPermissions/m:field", ns):
            obj, field = node.text.split(".")
            assert (sf / f"objects/{obj}/fields/{field}.field-meta.xml").exists(), node.text
    mule = (integrations / "mulesoft/src/main/mule/crm-system-api.xml").read_text()
    tree = ET.parse(integrations / "mulesoft/src/main/mule/crm-system-api.xml")
    assert not any(node.tag.rsplit("}", 1)[-1] == "until-successful" for node in tree.iter())
    assert 'refreshTokenWhen="#[attributes.statusCode == 401]"' in mule
    assert 'protocol="HTTPS"' in mule
    assert 'insecure="true"' not in mule
    print(
        json.dumps(
            {
                "status": "SOURCE_CHECKS_PASSED",
                "xml_files_parsed": len(xml_files),
                "json_files_parsed": len(json_files),
                "python_files_parsed": len(python_files),
                "n8n_credentials_in_export": False,
                "vendor_compilation": "NOT_EXECUTED",
                "vendor_runtime_tests": "NOT_EXECUTED",
                "provider_acceptance": "OPEN",
                "mule_jvm_retry_properties": "NOT_OBSERVED",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
