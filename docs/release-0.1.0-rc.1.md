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

The original source commit is [`7777b75497d840a97e53d6693d1ab60177cde0d5`](https://github.com/mehdisafer/crm-order-workflow-agent/commit/7777b75497d840a97e53d6693d1ab60177cde0d5). Its local suite contained 91 passing tests, zero failures and zero skips. `docs/evidence/source-manifest.json` preserves that historical scope. The continuation's full local suite again passed 91 tests with zero failures/skips in 27.65 seconds. Its source identity and rerun are recorded separately in the evidence index; original evidence is not silently rebound to changed source.

The 14 November continuation adds actual Firefox qualification and a successful Mule Maven package build. The browser exposed an invalid HTML identifier pattern and misleading historical-date/quantity labels; these were corrected and exercised through the actual interface. Six final desktop/mobile images show the completed case and its readback, with no page, console, HTTP or request errors and no horizontal overflow. The Mule build explicitly selects 4.9.24, resolves the pinned connector artifacts and retains unresolved external configuration/TLS and stream-validation warnings. These observations do not validate an actual Salesforce org or running Mule server.

The same continuation qualified the actual n8n 2.47.5 trigger: inactive export import, two separate local credentials bound outside the export, missing/wrong credential refusals, successful intake, duplicate delivery yielding one case, denied requester approval, distinct approval and Temporal completion with matching readback. The local runtime's initial registration and proxy-routing failures are retained. The versioned export remains inactive and contains no credential values or IDs.

## Release status

Prepared candidate on [PR #2](https://github.com/mehdisafer/crm-order-workflow-agent/pull/2); **not merged into main, not a public GitHub release and not full P06 acceptance**. GitHub jobs failed before runner allocation and any test step, so the reference-container and CI Chromium gates remain open. The successful local Firefox profile is identified separately. No version tag, licence grant, paid resource or visibility change is implied by this file. Actual Salesforce/MuleSoft execution and the remaining qualification/publication decisions are tracked in [acceptance.md](acceptance.md).

## Upgrade and rollback

This is schema version 1 with no prior application release. Run the migration once, seed only the explicit demo profile and keep API/worker schema versions aligned. Future changes must preserve existing workflow histories and effect identities. Roll back compatible application code after stopping new intake and accounting for in-flight effects; do not delete the outbox or reset keys. Database and remote-state recovery follow [operations.md](operations.md).
