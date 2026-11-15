# Acceptance and remaining work

Updated 15 November 2026. The **local reference is qualified**, including the real hosted container and browser execution. The complete P06 provider scope is **not accepted** until an authorized Salesforce/MuleSoft run satisfies its external requirements. No synthetic reference result, source parse or Maven build closes that gate.

## Qualified combined revision

Source: `4882add901422deeb2c374d5c98eaa273f30d2d7`.

CircleCI pipeline: `a13c8564-8c4c-41ef-91a7-d93ce04f8337`.
Workflow: [CI](https://app.circleci.com/workflow/1cdf13f5-ded8-4ab3-857c-301fd44e8e8f).
All three jobs completed successfully: core contracts/security, real Temporal recovery, and reference container/browser deployment.

This combined revision includes the maintainer-selected Apache-2.0 licence, NOTICE, package metadata and their regression tests from the application candidate. The licence synchronization was reviewed and merged through PR #6 before requalification. No licence was invented by the CI process.

## Requirement-to-evidence map

| Requirement | Observed evidence | Boundary |
|---|---|---|
| Typed intake, policy, API, adapter contracts and licence metadata | 82 core tests; zero failures/errors/skips | Synthetic/reference systems |
| Separate approval of the exact plan | Actual browser request, requester cannot approve, distinct approver submits the displayed hash | Browser identities are automated test principals, not real human wait-time observations |
| Durable execution and uncertain writes | 12 real Temporal tests; replay and guarded effect assertions | Not live Salesforce history |
| Worker restart | Three independent trials, 30-second bound, timings/history retained, one CRM and one inventory effect | Not an automatic retry that discards failed trials |
| Reference deployment | Actual image build/import, PostgreSQL, Temporal, HTTP ERP, API/worker execution | Local synthetic deployment |
| Current business result | Two effects applied once; CRM date and reservation reread and matched | No payment or real order |
| Browser lifecycle | Form POST 202, separate approval 202, reconciliation 200, completed state and matching current readback | Not an API-only substitute for interaction |
| Rendered view | Six desktop/mobile screenshots; 390 px mobile width; no document-level overflow | Browser/version recorded in artifact |
| Browser confidentiality | No token retained in rendered DOM/input/storage/cookies; no external requests in the observed workflow | Bounded executed scenario, not proof of every possible threat |
| Static/security controls | Lint/format, secret/history scan, contract drift, provider source checks, component/licence audit and dependency audit | Provider source invariants are not runtime acceptance |

## Actual browser observations

The retained report records requester `demo-requester`, approver `demo-approver` and operator `demo-operator`; separate approval was verified. The requested date differed from the currently observed order date. Both final effects were `APPLIED`, with one observed attempt each. Proposal-snapshot labeling and the distinction between CRM order quantity and reserved inventory quantity were checked.

The browser submitted and approved the request through the rendered form. Authenticated queue readback was used only to choose a non-colliding synthetic date; no hidden API mutation replaced the UI. Browser console errors and JavaScript page errors were empty. Desktop and mobile captures both reported no horizontal document overflow.

The browser sandbox remained enabled. Neither `--no-sandbox` nor host-wide security relaxation was used to obtain the successful run.

## Evidence integrity

These SHA-256 values were computed from the downloaded, unmodified artifacts of the combined run:

| Artifact | SHA-256 |
|---|---|
| `core-evidence-4882add901422deeb2c374d5c98eaa273f30d2d7/core.xml` | `c9a1789e428aa4589e73792db00a686d15079729f7cccf4d44849bb248fa0b66` |
| `temporal-evidence-4882add901422deeb2c374d5c98eaa273f30d2d7/temporal.xml` | `4919ef02313caef7a22aee32a9edb6eb1f78b9a50ee2a82338381e24e30d5d18a` |
| `reference-evidence-4882add901422deeb2c374d5c98eaa273f30d2d7/evidence-local/browser/operator-browser.json` | `58af36daee5f76b743c3ac472879d4193d4f997c27bb81e9ef15dffb66bf5f92ae6` |

The run additionally retains actual images, business-smoke output, minimized Temporal histories, timing records and service logs. Artifact retention is finite; the hashes and this acceptance decision remain versioned. Earlier evidence under [evidence/](evidence/) retains its original source/runtime attribution.

## Failures corrected, not erased

- The original restart test exceeded its ten-second observation budget in CI. It now uses three independent measured runs, an explicit thirty-second recovery bound and an independent unchanged approval-expiry test. Activity retry limits and no-duplicate assertions were not removed.
- The bundled browser could not launch in the observed hosted environment. The reviewed system Chrome executes with sandboxing retained.
- A clipped screen-reader label outside the table scroll container widened the mobile document. The CSS now anchors that label within its containing block; it does not globally hide document overflow.
- A bare `--exercise` did not activate the paired-argument parser. CI now passes `--exercise true` and verifies `exercise_requested=true` in the actual report.
- The preceding API smoke had already applied the same delivery date. The browser fixture now chooses a different bounded date from observed synthetic state, rather than weakening the application's no-change rule.

Original failed runs remain failures. Their later corrections do not retroactively qualify them.

## CI and reproduction

The fast `.circleci/config.yml` uses Smarter Testing for the core profile and excludes only the Temporal-only files from discovery. The full `.github/workflows/ci.yml` executes core, Temporal and the complete reference deployment/browser profile. A green fast job is not sufficient to replace the full workflow.

Use the commands in the [README](../README.md), [operator guide](operator-guide.md), [operations guide](operations.md) and [provider installation guide](vendor-integration.md). Local identities and `.local/` data are private runtime fixtures and must not be committed.

## Still open

1. Execute the Salesforce adapter and running Mule provider in an explicitly authorized environment, with named permissions and bounded resources. Verify identifiers, errors, idempotency, approval and post-action readback against those real providers.
2. Qualify the selected deployment target operationally, including secrets, restore, monitoring and operator acceptance. The local reference is not a target-specific production certification.
3. Complete maintainer publication/branch-protection decisions. Licence selection is no longer pending: Apache-2.0 is present in the combined candidate.

Issue #1 remains open for the original provider criteria. No stable `v1.0.0` release or full-provider completion is asserted. Earlier n8n/Maven/Firefox/load/restore observations remain useful historical evidence, but are not counted as new executions in this hosted run.
