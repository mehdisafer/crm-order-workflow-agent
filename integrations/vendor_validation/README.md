# Vendor qualification tools

| Command | Scope | Expected prerequisite |
| --- | --- | --- |
| `python integrations/vendor_validation/check_sources.py` | Local source syntax and packaging invariants only | Python 3.12+ |
| `python integrations/mulesoft/scripts/verify_runtime.py --pid <explicit-Mule-PID>` | Observe the Java version and effective retry JVM properties without exposing other properties | Existing authorized Mule process and `jcmd` |
| `python integrations/salesforce/scripts/preflight.py` | Read real Salesforce object descriptions and capabilities via Mule | Explicit authorized endpoints and external credentials |
| `uv run python integrations/vendor_validation/fault_proxy.py …` | Drop one real upstream success response, retaining original evidence | Private HTTPS certificate, actual Mule URL, separate control token |
| `uv run python integrations/vendor_validation/live_acceptance.py --execute --output <new-directory>` | Actual API, Temporal, Mule, Salesforce, ERP readback; stale approval, denial, response-loss recovery | Already installed authorized synthetic environment |

Missing prerequisites return `BLOCKED`; they never activate mocks or count as integration passes. The live run retains its case IDs early and never deletes evidence or automatically cleans up provider state. Read [the full procedure](../../docs/vendor-integration.md) for the exact variables, tenant scope and remaining acceptance gates.

The live command uses one absolute `--max-seconds` deadline for setup, both preparation waits, execution and history collection. HTTP response streaming, RPCs and polling share that remaining budget. Original message IDs and received case IDs remain in the report if it expires.
