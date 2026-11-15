"""Check the selected Apache-2.0 licence and third-party metadata presence."""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory")
    parser.add_argument("--output", default="evidence-local/licence-check.json")
    args = parser.parse_args()

    packages = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    unknown = [
        item["Name"]
        for item in packages
        if str(item.get("License", "UNKNOWN")).upper() in {"", "UNKNOWN"}
        and item["Name"] != "crm-order-workflow-agent"
    ]

    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    project_licence = project.get("license")
    declared_files = project.get("license-files", [])
    licence_path = Path("LICENSE")
    licence_text = licence_path.read_text(encoding="utf-8") if licence_path.is_file() else ""
    project_issues = []
    if project_licence != "Apache-2.0":
        project_issues.append("project SPDX expression does not match Apache-2.0")
    if "LICENSE" not in declared_files:
        project_issues.append("project metadata does not include LICENSE")
    if not (
        licence_text.startswith("Apache License\nVersion 2.0, January 2004")
        and "END OF TERMS AND CONDITIONS" in licence_text
        and "APPENDIX: How to apply the Apache License to your work" in licence_text
    ):
        project_issues.append("missing or incomplete Apache-2.0 LICENSE text")

    result = {
        "check": "project_and_third_party_licence_metadata",
        "components_observed": len(packages),
        "unknown_third_party_licences": unknown,
        "project_licence": project_licence,
        "project_licence_file": "LICENSE",
        "project_licence_issues": project_issues,
        "status": "review_required" if unknown or project_issues else "metadata_present",
        "limitation": "Metadata presence is not licence compatibility or redistribution certification",
    }
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    if unknown or project_issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
