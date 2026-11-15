# CRM Order Workflow Agent

**An order exception should end with an observed business result, safe compensation, or explicit escalation.**

This synthetic industrial customer-service application resolves a customer and order, checks inventory, prepares an exact delivery-date change and waits for a separate approver. Temporal executes the CRM change and reservation, then rereads both systems. Uncertain writes are reconciled using stable effect identities. Compensation must respect later human changes.

No payments, real customer orders or commercial commitments are in scope. Reference adapters and fixtures are deliberately synthetic; provider source packages are not represented as live Salesforce or MuleSoft acceptance.

## Delivery status — 15 November 2026

**The complete local reference now has an executed hosted qualification**, beyond the initial core-only CircleCI pipeline. The licence is [Apache-2.0](LICENSE), with attribution in [NOTICE](NOTICE). The candidate remains `0.1.0`; no full-provider or production V1 release is claimed.

| Executed gate | Observed result |
|---|---|
| Core contracts, policy, API and licence regressions | 82 tests passed, zero failures/errors/skips |
| Real Temporal profile | 12 tests passed, including independent restart trials and replay |
| Reference deployment | Real application image, PostgreSQL, Temporal and HTTP ERP started and exercised |
| Business effects | One applied CRM effect and one applied inventory effect; current readback matches |
| Actual browser workflow | Form submission, requester self-approval refusal, separate approval and reconciliation executed |
| Desktop/mobile view | Six captures; no document-level horizontal overflow at 390 px; no JavaScript or console errors |
| Source/dependency checks | Lint, contracts, component/licence checks and dependency audit completed in the full workflow |
| Salesforce / running Mule provider | Still requires authorized provider deployment and acceptance |

Qualified combined source: `4882add901422deeb2c374d5c98eaa273f30d2d7`. The Apache metadata changes from the application branch were merged into the independently qualified CircleCI candidate and tested again; they were not overwritten.

[Acceptance and proof](docs/acceptance.md) · [Hosted qualification](https://app.circleci.com/workflow/1cdf13f5-ded8-4ab3-857c-301fd44e8e8f) · [Architecture](docs/architecture.md) · [Operator guide](docs/operator-guide.md)

## Run a local smoke

Use Python 3.12 and uv. The lock defines the reviewed dependencies.

```bash
git clone https://github.com/mehdisafer/crm-order-workflow-agent.git
cd crm-order-workflow-agent
uv sync --locked
uv run --locked python -m crm_workflow.cli smoke
```

The smoke uses an isolated real Temporal service and synthetic business state, with a distinct approver and both-state verification. It writes `evidence-local/smoke.json`. The first run may download the official Temporal test-server binary. It does not require Salesforce credentials, an external LLM or a paid provider account.

While the delivery PR is not yet merged, use the `circleci-project-setup` branch for this consolidated candidate. Do not assume that a presentation-only default branch contains the application.

## Run and inspect the reference deployment

The [operator guide](docs/operator-guide.md) contains role-based interactive operation. [Operations](docs/operations.md) covers state, recovery and restoration; [provider installation](docs/vendor-integration.md) describes the external boundaries.

The CI deployment uses the repository's own commands, not replacement business mocks:

```bash
uv run python -m crm_workflow.cli init-demo
uv run python deploy/prepare_reference.py
docker compose --env-file .local/compose.env -f deploy/compose.yaml config --quiet
docker compose --env-file .local/compose.env -f deploy/compose.yaml -f deploy/compose.erp-http.yaml --profile erp-http up --build --wait --wait-timeout 180
uv run python deploy/reference_smoke.py
```

These commands create local synthetic identities and start the explicit local stack. Keep `.local/` private. Do not commit its credentials or reuse them as production identities. Stop only this stack with the same Compose files and profile when finished.

## Tests and CI

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -m 'not temporal and not vendor and not load'
RUN_TEMPORAL_TESTS=1 uv run pytest -m temporal
```

`.circleci/config.yml` runs the fast core suite through Smarter Testing. Its discovery includes new core regression files and excludes the two Temporal-only files; filtering away every test in a discovered file is not reported as a pass. `.github/workflows/ci.yml` separately runs core, real Temporal and the complete container/browser deployment.

The browser qualification uses a fresh isolated Chromium instance with its sandbox retained. It creates the request through the actual form, changes to a different approver, executes the workflow, and reconciles through the rendered UI. It selects a new synthetic delivery date from observed state so that the preceding API exercise does not accidentally turn the browser scenario into a legitimate no-change request.

Three independent restart trials are bounded to 30 seconds and retain timing and history. This does not weaken the separate approval-expiry test, activity retry budget or no-duplicate-effect assertions.

## Boundaries and historical evidence

Current integration evidence is identified in [acceptance](docs/acceptance.md). Earlier Firefox/n8n/Maven/restore exercises and their original failures remain in [versioned evidence](docs/evidence/). Historical counts are not added to the current test run.

A successful synthetic HTTP ERP deployment is not Salesforce tenant verification. A Maven-built Mule source package is not acceptance of a running Mule provider. The full acceptance issue remains open for those provider obligations and any target-specific operational acceptance. Publishing the source does not certify a production deployment.
