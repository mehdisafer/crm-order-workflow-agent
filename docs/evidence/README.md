# Evidence index

Evidence describes the system that actually ran. The source manifest identifies the delivered implementation; a hash demonstrates content agreement, not certification. No vendor result is inferred from the local tests.

| File | Observation |
| --- | --- |
| `tests.xml` and `tests.log` | Original full-suite output; inspect the tests/skips/failures and execution command |
| `initial-suite-failure.xml` and `.log` | Retained first consolidated run: an outdated orphan-effect fixture and an undersized recovery harness deadline; corrected before delivery, then rerun |
| `local-smoke.json` | Real Temporal workflow, synthetic CRM/ERP, distinct approval and final readback |
| `http-smoke.json` | Actual loopback API, worker, Temporal and ERP HTTP service; duplicate intake, denied requester approval, successful separate approval and reread |
| `local-load.json` | Parameters, predeclared thresholds, per-case measurements, two worker processes, resource scope and unmetered cost statement |
| `postgres-restore.json` | PostgreSQL version, 16 concurrent duplicate deliveries yielding one case, logical restore and restored-state reconciliation |
| `dependency-audit.json` | Original pip-audit output against locked runtime requirements |
| `components.json` | Observed package versions, authors, URLs and declared licence metadata, including the repository's intentionally undecided licence |
| `licence-check.json` | Third-party licence metadata presence check; project licence remains an explicit decision |
| `vendor-preflight.json` | Original blocked provider preflight; required environment was absent |
| `operator-browser.json` | Browser execution status; local Chromium was blocked by the executor's socket policy |
| `ci-observation.json` | GitHub run and job observations, including startup failures with no runner or executed steps; no CI success is inferred |
| `source-manifest.json` | Source commit/tree, file digests, commands and qualification scope |

The final evidence commit records the test counts and current CI links. A file listed here as a release deliverable must exist before the candidate is published. Generated `.local/` credentials, raw provider access tokens and actual private tenant payloads never belong in this directory.

The final local suite completed **91 tests, zero failures and zero skips**, in 43.51 seconds, including two deployment-configuration regressions added after review. GitHub's initial PR run failed before job execution: all three jobs reported runner ID 0, an empty runner name and no steps. Job-log retrieval returned no stored log. The connector does not expose the job annotations needed to establish the platform-side reason; the separate browser has no signed-in access to this private repository. Billing, runner policy and account settings were not changed. The PR therefore remains open and the container/browser gates remain unqualified.

## Scope of observed measurements

The recorded local load completed 24/24 cases with two separate worker processes, zero duplicate effects, approximately 8.03 seconds total and approximately 7.55 seconds automatic p95. The human approval in this exercise is an automated fixture with an explicitly measured short delay; it is not a measurement of real human response time. Python resource measurements cover the driver process only, not total host or Temporal resources. No provider or external-LLM call was made and no currency cost is inferred.

The isolated PostgreSQL exercise used PostgreSQL 16.2 supplied by the optional `pgserver==0.1.4` test helper. The production/reference image is a distinct pinned target. Logical restore preserved the tested case, event, outbox and source-effect records and the restored system's readback matched. This does not restore Salesforce or Temporal history from the application database; their recovery procedures are separate.

## Reproduce

```bash
RUN_TEMPORAL_TESTS=1 uv run --locked pytest -q --junitxml=docs/evidence/tests.xml
uv run --locked python -m crm_workflow.cli smoke --output docs/evidence/local-smoke.json
uv run --locked python scripts/load_profile.py --cases 24 --workers 2 --concurrency 4 --output docs/evidence/local-load.json
uv run --locked --with pgserver==0.1.4 python scripts/postgres_profile.py
uv run --locked python integrations/vendor_validation/check_sources.py
```

The HTTP/container and browser commands are in [operations.md](../operations.md). A failed or blocked profile stays visible and does not become a passing result by omission.
