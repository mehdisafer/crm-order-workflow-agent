# Reference deployment and operational runbooks

## Deployment scope and evidence

The deployment target is one Linux host with Docker Compose: a PostgreSQL business database, one persistent Temporal development server, an API and one or more workers. Synthetic inventory can run through its HTTP API. n8n and Prometheus are optional profiles. No Salesforce tenant, MuleSoft runtime, cloud account, public listener or paid resource is created by this repository.

The original authoring executor had no Docker and early GitHub Actions attempts failed before runner assignment; their results remain in [historical CI evidence](evidence/ci-observation.json). Actual hosted qualification subsequently succeeded: [release-source main CI 43770254516](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43770254516) at `cdf3c0e` and [post-release main CI 43772725456](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43772725456) at `4dc6e2a` each passed Core, Temporal and Reference container jobs, including Docker build, PostgreSQL/HTTP ERP, synthetic business readback and Chrome desktop/mobile exercise. These are verified *reference* executions, not a running MuleSoft/Salesforce provider deployment.

The original isolated Python/Temporal and HTTP profiles remain in [historical evidence](temporal-runtime.md) and [HTTP smoke](evidence/http-smoke.json). Newer hosted CI executed the business reference alongside independent Core and real Temporal jobs. After post-release PR #9, the Temporal profile passed 12 cases including three separate bounded worker-restart trials; no provider acceptance is implied.

## Start the reference environment

Install Docker with Compose v2 and uv. From the repository root:

```bash
uv sync --locked
uv run python -m crm_workflow.cli init-demo
uv run python deploy/prepare_reference.py
docker compose --env-file .local/compose.env -f deploy/compose.yaml config --quiet
docker compose --env-file .local/compose.env -f deploy/compose.yaml up --build -d
```

The identity and secret setup commands refuse to overwrite existing credentials. If they have already run, continue from the Compose command. Do not print `docker compose config` without `--quiet`: expanded environment values contain credentials.

If a previous revision generated `compose.env` before it contained the webhook and ERP variables, preserve the existing credentials and pass `--env-file .local/demo.env --env-file .local/compose.env` instead. These files provide interpolation values; only the variables explicitly listed for each service are injected into its container.

The operator view is at `http://127.0.0.1:8000`; use the requester, approver and operator tokens from the local token file. Temporal UI is at `http://127.0.0.1:8233`. These ports bind only to loopback. Database and gRPC ports are not published. The internal bridge permits the deliberately configured vendor endpoints in a later provider profile; it does not publish a business service.

For the synthetic ERP HTTP boundary, start with the overlay:

```bash
docker compose --env-file .local/compose.env \
  -f deploy/compose.yaml -f deploy/compose.erp-http.yaml \
  --profile erp-http up --build -d
uv run python deploy/reference_smoke.py
```

The bounded smoke script rejects non-loopback URLs and a non-demo profile. It uses two distinct local principals, verifies requester approval refusal, repeats the intake message, waits for Temporal, and rereads the recorded CRM and inventory effects. Automatic fixture approval measures no real human waiting time.

The base profile uses the original synthetic CRM and ERP implementations in the database. The HTTP overlay exposes the same original synthetic ERP through a real authenticated HTTP service. Both profiles remain visibly synthetic. Setting `profile=salesforce` requires explicit MuleSoft and ERP endpoint configuration and is not achieved by renaming these services.

### Browser demonstration

`deploy/capture_operator.mjs` opens the actual operator view and captures the overview, case detail and reconciliation at 1440×1100 and 390×844. Its default mode authenticates an operator and selects an existing case. `--exercise true` also creates a synthetic request through the real form, switches to the separate approver credential, approves the displayed plan, waits for completion and requests current readback through the UI. No request, API response or page data is mocked.

The script permits only loopback demo endpoints, uses normal headless browser launches, and records the selected engine, source hashes, screenshot hashes, page/console/network errors, horizontal overflow, credential-input clearing and empty browser storage. `--engine chromium` is the default; `--engine firefox` and `--engine webkit` explicitly select distinct rendering engines. An explicitly provided `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` selects an already installed Chromium. No sandbox-disabling launch flags are added.

The [original Firefox run](evidence/firefox-ui/README.md) passed the synthetic form/approval/readback scenario and retained six screenshots; the first isolated Chromium launch was [blocked](evidence/operator-browser.json). Subsequently the [release-source hosted CI](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43770254516) and [post-release hosted CI](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43772725456) both passed actual Chrome reference journeys with desktop/mobile captures, separate approval, matching readback and no horizontal viewport overflow. These distinct evidence scopes do not qualify Salesforce/MuleSoft identities, permissions or effects.

To reproduce the complete synthetic scenario without requiring a pre-existing stack:

```bash
mkdir -p .local/browser-tools
cp deploy/browser/package.json deploy/browser/package-lock.json .local/browser-tools/
npm ci --prefix .local/browser-tools --ignore-scripts --no-audit --no-fund
.local/browser-tools/node_modules/.bin/playwright install firefox
uv run --locked python deploy/qualify_operator.py \
  --engine firefox --output evidence-local/browser-firefox
```

`qualify_operator.py` creates fresh credentials and separate application/ERP SQLite databases in a private ignored session directory. It starts a real Temporal development server, API, HTTP ERP, worker and browser as children of one command, all on loopback, and stops its children when the bounded exercise ends. It ignores inherited `P06_*` settings before constructing its explicit demo environment; ordinary proxy/download settings are retained. This placement also works in executors that isolate loopback between commands. It does not overwrite existing local identities. Private session logs and databases stay outside the evidence directory.

To capture an already running reference stack, install the intended browser engine and run:

```bash
node deploy/capture_operator.mjs --modules .local/browser-tools/node_modules \
  --engine firefox --output evidence-local/browser-existing
```

Add `--exercise true` only when a new synthetic request with automated distinct approval is intended. The scenario uses `CUST-001` / `ORD-1001` and selects a future date **different from the currently observed order date**, to avoid a legitimate `NO_CHANGE_NEEDED` result after a prior reference smoke. An explicit `--requested-date YYYY-MM-DD` must also be a permitted, different date. Browser binaries are development-only, not part of the production Python image. Historical harness changes and failures are retained in [the evidence index](evidence/README.md).

## Secrets and privileges

`init-demo` is restricted to `profile=demo` with a persistent local SQLite URL. It checks this configuration before opening any store or creating credentials, seeds that SQLite fixture before issuing identities, refuses existing credential paths (including symbolic links), and creates private credential files exclusively with mode 0600. It generates bearer tokens, a webhook secret and the ERP token. `prepare_reference.py` generates the application database password and n8n encryption key. For a separate PostgreSQL reference deployment, use the documented one-shot migration/seeding service; never point `init-demo` at a provider or remote database. Generated files live only in ignored local paths. The image excludes those paths, the Git directory, local databases and evidence artifacts.

The PostgreSQL bootstrap identity owns migrations. A separate `p06_app` identity receives table DML and sequence privileges through default grants; it does not receive schema creation or role administration rights. API, worker and ERP containers use that application identity. Compose explicitly selects their environment variables: the owner database URL belongs only to `migrate`, the webhook secret only to the API, and the ERP token to API, worker and ERP. It does not import the complete local secret file into these containers. The n8n encryption key belongs only to n8n, and no LLM credentials are injected.

The PostgreSQL health check connects over TCP so its temporary, socket-only bootstrap server cannot admit migrations before role creation and default grants finish. The one-shot `migrate` service completes before consumers start, preventing concurrent schema creation. Containers run without added capabilities and with a read-only application filesystem.

Local principal files retain mode 0600. Compose runs application processes with the UID/GID captured by `prepare_reference.py`, allowing the exact mounted principal file to be read without broadening host access. Database secret files are readable inside their narrowly mounted containers; their host directory is private. On a target host, use an external secret manager and rotate each technical identity independently.

Salesforce and MuleSoft require their own restricted service principals and verified server-side permission tests. Local bearer-token refusals do not prove provider permissions. See [vendor installation](vendor-integration.md).

The explicit `deploy/compose.salesforce.yaml` overlay switches API and worker to the real MuleSoft gateway and leaves only inventory synthetic. It explicitly opts in to **plaintext `http://erp:8001` only for the internal synthetic Docker ERP**; an actual ERP deployment must instead use an HTTPS endpoint with verified certificates (optionally `P06_ERP_CA_FILE` for a reviewed private CA) and cannot use this HTTP exception. After authorised vendor installation, put `P06_MULE_URL` and `P06_MULE_TOKEN` in an external local env file, bind the operator principals to the exact Salesforce tenant, and pass both env files to Compose:

```bash
docker compose --env-file .local/compose.env --env-file .local/vendor.env \
  -f deploy/compose.yaml -f deploy/compose.salesforce.yaml \
  --profile erp-http up --build -d
```

Do not run the local reference smoke against this profile: it deliberately refuses provider mode. Use the separately scoped provider acceptance procedure instead. No vendor deployment was performed while preparing this overlay.

## Optional peripheral services

Add `--profile n8n` to start the pinned n8n image on loopback port 5678. Complete its normal owner setup and import `integrations/n8n/order-intake.workflow.json`. The export is inactive and contains no credentials; bind the inbound and outbound credentials in the authorised runtime. Use a dedicated requester-only service principal. n8n does not own approvals, reservations or retries of the business saga. Telemetry and execution-data persistence are disabled in this reference configuration. Its sustainable-use terms remain applicable.

Add `--profile monitoring` for Prometheus on loopback port 9090. It uses the generated operator token to scrape tenant-scoped `/metrics`; that token does not appear in the committed configuration. The optional reference Prometheus storage is temporary and is not a long-term monitoring archive.

No Terraform resource is fabricated to satisfy a technology checklist. Compose expresses the selected single-host resources. Terraform becomes appropriate when an authorised target infrastructure and provider are selected; Salesforce metadata and MuleSoft applications use their supported vendor deployment procedures.

## Limits and service objectives

The reference defaults cap workers at eight concurrent activities, CRM and ERP at four concurrent calls each, and the Temporal task queue at twenty activities per second. Shared database leases enforce system limits across workers. All workers must keep the same queue rate configuration. The container limits bound each process's memory/CPU and the application PID count; these are reference limits, not capacity guarantees.

Operational objectives for this small demonstration are:

- Accepted intake is durably stored before HTTP 202. A storage failure must not be acknowledged as accepted.
- Every accepted case reaches a visible state; stalled outbox and reconciliation-required cases receive an operator action.
- A completed case includes matching remote readbacks. A local completion flag is insufficient evidence.
- Human waiting is measured separately from system execution and has an explicit expiry.
- No duplicate message or recovered acknowledgement creates another business effect.

The bounded load profile and its observed environment determine useful latency and throughput numbers. This architecture alone proves neither high availability nor scalability. The Temporal development server is a single point of failure, and its in-host persistence does not protect against loss of the host disk.

## Outbox backlog or dead events

`P06OutboxBacklog` triggers above twenty pending events for five minutes; `P06DeadOutbox` triggers for any dead event. These conservative reference thresholds identify loss of progress without paging on a brief restart. Adjust them only after measuring normal intake and provider quotas.

1. Check whether the worker and Temporal service are running and whether the transactional database is reachable.
2. Inspect the original case ID, outbox kind, delivery attempts and safe error type. Keep the original workflow/effect IDs.
3. If a start response was lost, describe `case-{case_id}` before considering any new execution. The dispatcher performs this check automatically during normal retry.
4. Correct the identified configuration or outage, then use `python -m crm_workflow.cli replay-outbox EVENT_ID` for a dead, undelivered event. Do not insert a second event with another identity.
5. Confirm the original event is acknowledged and reread the case. Replaying an outbox message is not authorisation to expand an approved plan.

## Uncertain effect or compensation conflict

`P06ReconciliationRequired` identifies a case whose effects cannot be safely treated as complete or undone.

1. Stop manual replay of that case. Record its correlation ID and affected CRM order and reservation keys.
2. Read the effect ledger and the current CRM/ERP objects. A timeout or worker crash may follow a committed remote write.
3. Use the operator's reconcile action to capture the current state. It preserves historical workflow outcome and makes drift visible.
4. If a human or another process changed the order after the workflow's effect, preserve that newer state. The previous value is not an unconditional rollback target.
5. Resolve the business decision with a new, explicitly scoped request if needed. Do not extend an expired approval or replace its hash in storage.

Automatic compensation is limited to the original approved delivery-date field, exact observed revision and original effect. A committed stock reservation is reconciled before a CRM compensation is attempted. An impossible or expired compensation remains visible.

## Metrics unavailable

Check `/health/live` for process liveness, then `/health/ready` with the authorised bearer identity for database readiness. These endpoints do not prove Salesforce, MuleSoft or worker health. Check the operator metric token and exact tenant binding. Do not remove authentication or expose the database to make the probe green.

The metric endpoint exports route templates, status codes, durations, case counts by state and outbox counts. It excludes arbitrary URL paths, case IDs and tenant strings as labels. The Prometheus rules contain runbook pointers; no external alert recipient is configured or contacted.

## Stop and resume

Stop intake first, allow activities to finish, then stop infrastructure:

```bash
docker compose --env-file .local/compose.env -f deploy/compose.yaml stop api
docker compose --env-file .local/compose.env -f deploy/compose.yaml stop -t 60 worker
docker compose --env-file .local/compose.env -f deploy/compose.yaml stop
```

Resume with the same Compose configuration and volumes. Pending outbox entries, approvals, ledgers and histories remain. `down --volumes` deletes those stores and is not a routine stop command. Forced termination leaves journaled effects for reconciliation; it does not assert rollback.

## Backup and restoration

There are two independent stores to protect: the business database and Temporal history. Backing up only one can produce a history/state mismatch. The current reference recovery procedure is a maintenance-window snapshot:

1. Stop intake and workers as above, then stop Temporal after active activities have drained.
2. Export PostgreSQL with `pg_dump --format=custom` using the maintenance identity. Preserve original case, effect and outbox keys.
3. Copy the stopped Temporal history database from its named volume. Do not copy an active SQLite WAL file as if it were a complete database.
4. Record the application commit, image versions, schema version, Temporal version, configuration identifiers and checksums beside the backup. Back up secrets through the chosen secret manager, separately from public evidence.
5. Restore both stores into a separate, newly named isolated stack. Reconnect only synthetic services for the rehearsal. Replay histories, inspect pending effects and run the operator reconciliation before any target is allowed to resume writes.

For the SQLite business profile, the CLI uses SQLite's online backup API and performs an independent restore integrity/count check:

```bash
uv run python -m crm_workflow.cli backup .local/workflow.db .local/workflow-backup.db
uv run python -m crm_workflow.cli restore-check .local/workflow-backup.db
```

This local check is not a PostgreSQL disaster-recovery rehearsal. PostgreSQL restore and provider-state reconciliation must be executed and recorded on the authorised target before claiming an operational RPO/RTO. No numerical RPO/RTO has been validated for a provider deployment.

## Migration and rollback

Schema version 1 is the initial migration. Run migrations once with the maintenance identity before consumers start. The application refuses an unsupported schema version. Do not use automatic `create_all` in each application process as an upgrade strategy.

For a code-only rollback compatible with schema and workflow histories: stop intake, drain or stop workers, restore the previous immutable image, replay representative histories, then resume. For a future schema change, add a reviewed forward migration, data-preservation plan and explicit downgrade or restore procedure. Restoring a database does not undo Salesforce/ERP mutations; reconcile those effects separately.

## Build, dependency and publication gates

CI uses the locked Python dependencies, checks Ruff and versioned-contract drift, runs meaningful core and actual Temporal tests, scans the worktree/reachable history for high-confidence credential patterns, audits runtime dependencies and records component licence metadata. Upstream HTTP Retry-After hints are bounded at 24 hours and nonfinite values are not forwarded into circuit/Temporal timers; this is a **local safety ceiling**, not a claim about live provider quota policies. Worker JSON logs preserve known static application events and allowlisted fields but redact unrecognized/external messages before formatting, without expanding third-party arguments. The focused scanner does not prove the absence of every possible secret; the publication review also covers issue/PR text, logs and artifacts.

Image tags and action commit SHAs are explicit. Registry digests and actual image pull/build outcomes must be recorded from the deployment environment; no unobserved digest is invented. The original project source is licensed under Apache-2.0 (see root `LICENSE`); this does not replace third-party terms or establish redistribution compliance for a built container.

## Official references used for the prepared deployment

- [Temporal CLI Docker image and development mode](https://hub.docker.com/r/temporalio/temporal)
- [Temporal CLI 1.10.1 release](https://github.com/temporalio/cli/releases/tag/v1.10.1)
- [PostgreSQL official image](https://hub.docker.com/_/postgres)
- [Python official image](https://hub.docker.com/_/python)
- [uv Docker integration and frozen/locked installs](https://docs.astral.sh/uv/guides/integration/docker/)
- [n8n 2.47.5 release](https://github.com/n8n-io/n8n/releases/tag/n8n%402.47.5)
- [Prometheus 3.16.0 release](https://github.com/prometheus/prometheus/releases/tag/v3.16.0)
- [Playwright supported CI installation](https://playwright.dev/docs/ci)
- [Playwright screenshot API](https://playwright.dev/docs/screenshots)
