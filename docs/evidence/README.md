# Evidence index

Evidence describes the system that actually ran. The source manifest identifies the delivered implementation; a hash demonstrates content agreement, not certification. No vendor result is inferred from the local tests.

| File | Observation |
| --- | --- |
| `tests.xml` and `tests.log` | Original baseline full-suite output; inspect the tests/skips/failures and execution command |
| `continuation-tests.xml` and `.log` | Full local suite rerun after the continuation's source changes; kept separately from the baseline output |
| `continuation-checks.json` | Observed Ruff, formatting, JavaScript syntax, vendor source and contract-drift results |
| `continuation-review.json` | Source/history secret scan, local links and digests; original Maven log whitespace findings are preserved and separated from the passing source/document diff check |
| `initial-suite-failure.xml` and `.log` | Retained first consolidated run: an outdated orphan-effect fixture and an undersized recovery harness deadline; corrected before delivery, then rerun |
| `local-smoke.json` | Real Temporal workflow, synthetic CRM/ERP, distinct approval and final readback |
| `http-smoke.json` | Actual loopback API, worker, Temporal and ERP HTTP service; duplicate intake, denied requester approval, successful separate approval and reread |
| `local-load.json` | Parameters, predeclared thresholds, per-case measurements, two worker processes, resource scope and unmetered cost statement |
| `postgres-restore.json` | PostgreSQL version, 16 concurrent duplicate deliveries yielding one case, logical restore and restored-state reconciliation |
| `dependency-audit.json` | Original pip-audit output against locked runtime requirements |
| `components.json` | Observed package versions, authors, URLs and declared licence metadata, including the repository's intentionally undecided licence |
| `licence-check.json` | Third-party licence metadata presence check; project licence remains an explicit decision |
| `vendor-preflight.json` | Original blocked provider preflight; required environment was absent |
| `operator-browser.json` | Historical Chromium attempt, blocked by the executor's socket policy; preserved unchanged |
| [`firefox-ui/README.md`](firefox-ui/README.md) | Actual browser journey and independent Temporal/HTTP ERP observation; six final desktop/mobile screenshots, original failed runs and capture/source digests |
| [`mule-build-20261114/README.md`](mule-build-20261114/README.md) | Actual Mule package build, exact toolchain, resolved dependency tree, bundled artifact inventory and unresolved warnings; server/provider execution remains open |
| `n8n-qualification.json` and `.log` | Actual n8n 2.47.5 import and authenticated trigger-to-Temporal completion; synthetic business systems only |
| `n8n-qualification.initial.*`, `.proxy-failure.*` and `.install*` | Original registration, proxy-routing and installation attempts retained with the final result |
| `n8n-qualification.harness-review.json` | Executed/final harness digests and the separate process-cancellation regression; full n8n scenario was not rerun after that cleanup-only patch |
| `ci-observation.json` | GitHub run and job observations, including startup failures with no runner or executed steps; no CI success is inferred |
| `source-manifest.json` | Historical baseline source commit/tree, file digests, commands and qualification scope |
| `continuation-manifest.json` | Continuation source commit/tree, evidence digests, actual rerun scope and explicitly identified post-execution harness changes |
| `continuation-ci-observation.json` | Continuation source/PR workflow status at capture time; recorded independently from local checks |
| `publication-readiness.json` | Subsequent publication authorization, observed main overview merge, preserved raw evidence and exact output-routing/source differences; no additional business-runtime result |
| `publication-recheck-20261115.json` | Connector rerun accepted, attempt 2 still without a runner or steps; observed publication settings and the separate required-check trigger correction |

Each evidence record identifies its source and observation scope. A file listed here as a release deliverable must exist before the candidate is published. Generated `.local/` credentials, raw provider access tokens and actual private tenant payloads never belong in this directory.

The original qualified source is commit [`7777b75497d840a97e53d6693d1ab60177cde0d5`](https://github.com/mehdisafer/crm-order-workflow-agent/commit/7777b75497d840a97e53d6693d1ab60177cde0d5). Its [PR CI run](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43526218191) reproduces the startup failure recorded below. The continuation changes the Mule packaging inputs, browser UI/capture and qualification helpers. Its separate manifest binds the delivered source and new observations; the baseline manifest is not presented as proof for those changes. The continuation source is [`ea0f914dcf3a6cbf9a7d2c941a2369644bbad932`](https://github.com/mehdisafer/crm-order-workflow-agent/commit/ea0f914dcf3a6cbf9a7d2c941a2369644bbad932); its [PR CI run](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43594992909) again failed before any runner or step executed.

The baseline local suite completed **91 tests, zero failures and zero skips**, in 43.51 seconds, including two deployment-configuration regressions added after review. GitHub's initial PR run failed before job execution: all three jobs reported runner ID 0, an empty runner name and no steps. Job-log retrieval returned no stored log. The connector does not expose the job annotations needed to establish the platform-side reason; the maintainer handles the interface-only inspection. Billing, runner policy and account settings were not changed. The application PR remains open; the reference-container and CI Chromium gates remain unqualified.

## Continuation observations

The continuation's full local suite completed **91 tests, zero failures and zero skips**, in **27.65 seconds**. This is a new execution with original XML/log output, including the real Temporal profiles. One existing Starlette TestClient deprecation warning remains visible; it is not a test failure or a claim about future dependency compatibility.

Firefox 153.0 and locked Playwright 1.62.1 exercised the actual request form, separate approval, Temporal completion and operator readback. The final run has zero page/console/HTTP/request errors and zero horizontal page overflow at both recorded viewport widths. The served UI files and all six final PNGs remain unchanged. The capture-script digest agrees with the continuation source; its later default-output change is recorded separately below. The Python supervisor's post-capture environment-isolation change was checked statically and is also explicitly distinguished from the executed capture.

Mule Maven plugin 4.10.4, Maven 3.10.0 and Corretto 17.0.21 generated the application package for target 4.9.24, including the exact HTTP/OAuth connectors and 12 bundled JARs. The unresolved external-config/TLS and skipped stream-validation warnings remain in the original log. Packaging is observed; no Mule server or Salesforce org was exercised.

The real n8n 2.47.5 runtime refused missing/wrong inbound credentials with 403 and accepted the authenticated trigger with 202. Duplicate delivery mapped to one case. The application refused requester self-approval; a separate approver led to a completed Temporal workflow, two `APPLIED` effects with one attempt each, and matching readback. The recorded 1.177-second trigger-to-completion interval used an automated approval fixture, not a real human delay. All child services were stopped afterward. The versioned workflow export remained unchanged, inactive and credential-free.

## Scope of observed measurements

The recorded local load completed 24/24 cases with two separate worker processes, zero duplicate effects, approximately 8.03 seconds total and approximately 7.55 seconds automatic p95. The human approval in this exercise is an automated fixture with an explicitly measured short delay; it is not a measurement of real human response time. Python resource measurements cover the driver process only, not total host or Temporal resources. No provider or external-LLM call was made and no currency cost is inferred.

The isolated PostgreSQL exercise used PostgreSQL 16.2 supplied by the optional `pgserver==0.1.4` test helper. The production/reference image is a distinct pinned target. Logical restore preserved the tested case, event, outbox and source-effect records and the restored system's readback matched. This does not restore Salesforce or Temporal history from the application database; their recovery procedures are separate.

## Reproduce

```bash
RUN_TEMPORAL_TESTS=1 uv run --locked pytest -q --junitxml=evidence-local/tests.xml
uv run --locked python -m crm_workflow.cli smoke --output evidence-local/local-smoke.json
uv run --locked python scripts/load_profile.py --cases 24 --workers 2 --concurrency 4 --output evidence-local/local-load.json
uv run --locked --with pgserver==0.1.4 python scripts/postgres_profile.py --output evidence-local/postgres-restore.json
uv run --locked python integrations/vendor_validation/check_sources.py
```

The HTTP/container and browser commands are in [operations.md](../operations.md). A failed or blocked profile stays visible and does not become a passing result by omission.

Reproduction writes to the ignored `evidence-local/` directory. The original JSON, XML, log and image evidence under `docs/evidence/` retains its bytes and execution scope; Markdown indices are updated to explain later work. Subsequent publication preparation changes only the default report destinations in the browser/n8n helpers and adds PostgreSQL's `--output` option, alongside publication metadata and documentation. Source inspection, syntax/format checks and CLI help checks cover those helper changes. No new browser, n8n or PostgreSQL business run is inferred from that output-routing correction. See [publication readiness](publication-readiness.json) for the differences from the runtime-qualified source.
