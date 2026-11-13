# Release candidate 0.1.0-rc.1

## Business result

This candidate introduces a complete local order-exception desk: authenticated intake, customer/order resolution, typed delivery-date plan, independent approval, durable CRM/ERP saga, conditional compensation and observed-state reconciliation.

## Included

- Real Temporal orchestration with explicit activity budgets, persisted outbox dispatch and restart recovery.
- Transactional business evidence, tenant isolation, stable effect keys and conflict-aware compensation.
- Operator API and interface, signed direct webhooks, a synthetic ERP HTTP service and an optional constrained local-model interpreter.
- Salesforce custom objects/Apex/permission source, MuleSoft system API, inactive n8n export and a bounded actual-provider validation harness.
- Locked Python environment, container reference, CI checks, monitoring, operational procedures and original local qualification results.

## Verification

The [evidence index](evidence/README.md) links the exact source identity, original tests, local HTTP demonstration, load measurement, isolated PostgreSQL restore and dependency scan. The killed-worker test exits the process after the persistent synthetic CRM commit and before its response, then verifies one CRM effect and one reservation after replacement. This is a real durability test with an explicitly synthetic source system.

## Release status

Prepared candidate; **not a public GitHub release and not full P06 acceptance**. No version tag, licence grant, paid resource or visibility change is implied by this file. Actual Salesforce/MuleSoft execution, n8n runtime qualification and publication decisions remain open in [acceptance.md](acceptance.md).

## Upgrade and rollback

This is schema version 1 with no prior application release. Run the migration once, seed only the explicit demo profile and keep API/worker schema versions aligned. Future changes must preserve existing workflow histories and effect identities. Roll back compatible application code after stopping new intake and accounting for in-flight effects; do not delete the outbox or reset keys. Database and remote-state recovery follow [operations.md](operations.md).
