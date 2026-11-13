"""Check third-party licence metadata presence; do not select the project licence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory")
    parser.add_argument("--output", default="evidence-local/licence-check.json")
    args = parser.parse_args()
    packages = json.loads(Path(args.inventory).read_text())
    unknown = [
        item["Name"]
        for item in packages
        if str(item.get("License", "UNKNOWN")).upper() in {"", "UNKNOWN"}
        and item["Name"] != "crm-order-workflow-agent"
    ]
    result = {
        "check": "third_party_licence_metadata_presence",
        "components_observed": len(packages),
        "unknown_third_party_licences": unknown,
        "project_licence": "pending_explicit_maintainer_decision",
        "status": "review_required" if unknown else "metadata_present",
        "limitation": "Metadata presence is not licence compatibility or redistribution certification",
    }
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    if unknown:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
