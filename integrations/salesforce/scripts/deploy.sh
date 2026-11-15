#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 2 || ( "$2" != "--check-only" && "$2" != "--execute" ) ]]; then
  echo "Usage: deploy.sh <explicit-authorized-org-alias> --check-only|--execute" >&2
  exit 2
fi
p06_target="$1"
p06_mode="$2"
p06_source="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$p06_source"
# Never print org display: it can include the access token.
p06_org_check="$(sf data query --target-org "$p06_target" --query 'SELECT IsSandbox, OrganizationType FROM Organization' --json)"
printf '%s' "$p06_org_check" | python3 -c '
import json, sys
r = json.load(sys.stdin)
rows = r.get("result", {}).get("records", [])
if r.get("status") != 0 or len(rows) != 1:
    raise SystemExit("Cannot verify the selected org")
o = rows[0]
if not o.get("IsSandbox") and o.get("OrganizationType") != "Developer Edition":
    raise SystemExit("Only an explicitly authorized sandbox or Developer Edition org is supported")
'
if [[ "$p06_mode" == "--check-only" ]]; then
  sf project deploy start --target-org "$p06_target" --source-dir force-app --dry-run --test-level RunLocalTests --wait 20
else
  sf project deploy start --target-org "$p06_target" --source-dir force-app --test-level RunLocalTests --wait 20
fi
