# Operator guide

The desk follows an exception from intake to a bounded approval, observed CRM and inventory effects, and final readback. Aster Works is a fictional industrial group. Every supplied customer, order and note is synthetic.

The banner identifies the configured profile. **Synthetic reference · demo** means the local CRM implementation is in use. **Salesforce via MuleSoft · provider profile** means that the provider path was selected; that label does not prove that a vendor execution has passed. Read the case evidence and the project acceptance record separately.

## Start the local desk

From the repository root, install the locked environment and create isolated demo identities once:

```bash
uv sync --locked
uv run --locked python -m crm_workflow.cli init-demo
```

`init-demo` creates random credentials outside Git and refuses to overwrite an existing credential set. It also inserts synthetic data without replacing existing effects. Start Temporal and the worker using [the runtime guide](temporal-runtime.md), or use the reference deployment described in the README. The web process alone accepts requests but does not run the saga.

For a local API process:

```bash
uv run --locked uvicorn crm_workflow.api:app \
  --host 127.0.0.1 --port 8000 --no-access-log
```

Open [the operator desk](http://127.0.0.1:8000). Open `.local/tokens.json` privately and paste the appropriate credential into the connection form. Do not copy that file into issues, screenshots, build logs or shared evidence.

The default fixture creates three identities:

| Identity | Default roles | What it can do |
| --- | --- | --- |
| `requester` | `requester`, `operator` | Submit a request, read its tenant's cases and request readback. |
| `approver` | `approver`, `operator` | Approve or reject another identity's plan and request readback. |
| `operator` | `operator` | Read cases and request current system state. |

A provider deployment should issue only the necessary roles. An n8n intake identity needs `requester`, without `approver`. The HTTP API has no endpoint that directly executes CRM writes. Temporal activities run the server-side saga.

## Walk through one request

1. Connect as the requester and choose **New request**. In the demo profile, the form offers `CUST-001` and `ORD-1001`. Select a future delivery date within the configured policy window, different from the current date on the order. The default window is 90 days.
2. Keep the generated **Message ID**. It identifies this submission and must remain unchanged if the same message needs to be sent again. Submit the request. `202 Accepted` means the case and its outbox command were persisted; it is not evidence of a remote change.
3. Wait for **Awaiting approval**. The worker resolves the customer and order, reads availability and records a typed plan. Review the customer, order, SKU, quantity, before/after dates, CRM revision and inventory revision. The complete plan fingerprint is available under **Approved scope and plan fingerprint**.
4. Switch to the separate approver credential and reopen the case from the queue. Choose **Approve this plan** or **Reject**. The server refuses self-approval even if a principal happens to carry both roles. An approval refers to the displayed plan hash; it cannot widen the set of fields, change the target or extend the expiry.
5. Follow **What the systems reported**. The worker rechecks preconditions, applies the authorised CRM change, reserves stock and reads both systems again. The journal preserves prepared, uncertain, applied and compensated effects separately.
6. Inspect **Workflow and remote state**. A completed workflow has a recorded execution readback. An operator can choose **Read current state** to detect later human edits or other drift. This performs reads and appends the observation to the case; it does not apply another order change.

The queue refreshes every four seconds while the tab is visible and connected. It displays the bounded set returned by the service. Counts in the UI describe that returned set. Prometheus case gauges use database aggregates instead.

## Read the state accurately

| State | Meaning and operator response |
| --- | --- |
| `RECEIVED` | Intake is durable; the Temporal worker has not yet produced a plan. Check worker/outbox health if this persists. |
| `AWAITING_APPROVAL` | A plan exists and awaits a separate authorised decision. The server's expiry check remains authoritative. |
| `APPROVED` | The decision was recorded. Remote preconditions still have to pass. |
| `CRM_APPLIED` | The CRM effect was observed and matched the approved mutation. The stock step is not yet complete. |
| `STOCK_RESERVED` | The stock reservation was observed. Final readback is still required. |
| `COMPLETED` | Both systems matched the approved effects at workflow completion. A later readback can still reveal drift. |
| `NEEDS_CLARIFICATION` | The request did not resolve to one usable intent, customer or order. Read the reason; the implementation accepts a corrected request with a new message ID. It does not silently modify this case's original request. |
| `ESCALATED` | A business or provider condition prevents an authorised proposal, such as insufficient stock. |
| `APPROVAL_INVALIDATED` | Approval scope, expiry or a remote precondition no longer permits the intended write. |
| `EXPIRED` / `REJECTED` | The proposal did not receive a valid affirmative approval. |
| `COMPENSATED` | A conditional compensation was observed. Original effects remain visible; this is not a universal rollback. |
| `RECONCILIATION_REQUIRED` | A remote outcome or conflict needs investigation. Do not replay a write without checking its existing remote effect key. |
| `FAILED` | The bounded workflow could not finish without a recorded uncertain/applied effect. Consult the recorded reason and runbook. |

The **Effect journal** deliberately uses different language from the workflow state:

- **Prepared only** records an intended effect; it does not prove a remote write.
- **Outcome uncertain** means a request may have reached the remote system. The same effect key must be reconciled before another write.
- **Effect observed** includes the returned or reconciled remote snapshot.
- **Compensated** records an additional conditional effect; it does not erase the original operation.

CRM links are clickable only for HTTPS Salesforce domains. A `demo://` object remains an explicitly synthetic reference. Notes, API errors and JSON evidence are rendered as text, never interpreted as HTML or executable instructions.

## Handle an interrupted action

If submission times out, refresh the queue first. The case may already have been committed. If it is still absent, resend the same content with the same message ID. The service returns the original case for a matching delivery and rejects reuse with a different payload or requester.

If an approval response is lost, reopen the case before making another decision. A stale plan or a changed case state is refused by the server. The browser does not automatically retry mutations.

If the stock or CRM state changed after proposal, inspect the invalidation or compensation reason. A newer human change must remain visible and must not be overwritten with an older value. Use the incident procedure before any controlled outbox replay; the operator UI intentionally has no blind replay control.

## API boundary

Requests and responses use JSON. `OrderRequest` and `ApprovalRequest` reject additional fields. The server derives identity, tenant and roles from its external principal file. A body cannot select them.

| Endpoint | Authentication | Result |
| --- | --- | --- |
| `GET /health/live` | None | Minimal process liveness. |
| `GET /health/ready` | Bearer | Transactional storage readiness only. It does not probe Temporal, Salesforce or MuleSoft. |
| `GET /api/v1/session` | Bearer | Current principal and configured profile; no token or secret. |
| `GET /api/v1/openapi.json` | Bearer | The running API's generated contract. |
| `GET /api/v1/cases` | Bearer | `{schema_version, items}` for the authenticated tenant. |
| `POST /api/v1/cases` | Bearer, `requester` | Persist intake and outbox command; return the case with `202`. |
| `GET /api/v1/cases/{case_id}` | Bearer | Full authorised case, including effects and events. Cross-tenant identifiers return `404`. |
| `POST /api/v1/cases/{case_id}/approval` | Bearer, `approver` | Record `{plan_hash, decision}` with `202`; the core also enforces separation and expiry. |
| `POST /api/v1/cases/{case_id}/reconcile` | Bearer, `operator` | Submit `{}` to request current readback. The case must have an approved plan. |
| `POST /api/v1/webhooks/requests` | Timestamped HMAC | Persist intake using the configured webhook identity and tenant. |
| `GET /metrics` | Bearer, `operator` | Prometheus aggregates scoped to the credential's tenant. |

`POST` commands require `Content-Type: application/json`. The body limit defaults to 16,384 bytes and counts bytes received, including when `Content-Length` is absent or understated. Validation errors omit rejected input. Unexpected errors return an opaque request ID and do not reflect provider bodies or exception text.

### Signed webhook intake

n8n can use an externally bound Header Auth credential to forward the body to `POST /api/v1/cases`. The n8n export contains no credential values and does not own a second workflow state.

Other clients may use the dedicated HMAC route:

- `X-P06-Timestamp`: Unix time in seconds, within five minutes of the server.
- `X-P06-Signature`: hexadecimal HMAC-SHA256 over the exact bytes `timestamp + "." + raw_body`. A `sha256=` prefix is also accepted.
- The signing secret comes from `P06_WEBHOOK_SECRET`. An empty secret disables the route with `503`.
- The server authenticates the raw bytes before parsing JSON. Sign and send the same bytes; do not reformat JSON afterward.
- Signed repeats inside the freshness window are allowed. The transactional message-ID check provides delivery deduplication; the signature is not a one-time nonce.

The configured `P06_WEBHOOK_ACTOR_ID` and `P06_WEBHOOK_TENANT_ID` determine the intake scope. They are not accepted from the message body. Webhook intake can request a proposal; it cannot grant approval.

## Credentials, logs and metrics

The API loads `.local/principals.json` by default, or the path in `P06_AUTH_FILE`. It stores SHA-256 hashes, principal IDs, tenant IDs and explicit roles. Random high-entropy bearer tokens remain external to Git. An invalid or ambiguous principal document prevents startup. Rotate or revoke a credential by updating the protected file and restarting the API process; loading is deliberately not performed from caller-supplied paths.

The browser keeps its token only in memory. It uses no browser storage, cookie or URL parameter for authentication. Disconnecting or switching identity clears the displayed case data and request draft. Refreshing the page clears the token. Deploy beyond loopback only behind the authenticated reference network and HTTPS ingress described in the deployment guide.

The app emits request IDs, route templates, HTTP status and elapsed time. It does not log headers, request notes, credentials or raw provider exception bodies. Use `--no-access-log` with Uvicorn so its independent access logger does not record raw query strings.

Prometheus metrics are intentionally bounded:

| Metric | Interpretation |
| --- | --- |
| `p06_api_requests_total{method,route,status_code}` | Authenticated requests observed by this API process. Route labels use templates, never case IDs. |
| `p06_api_request_duration_seconds{method,route}` | HTTP latency. This excludes human approval wait and does not measure the complete workflow duration. |
| `p06_cases{state}` | Exact persisted case counts for the authenticated tenant. |
| `p06_outbox_pending` | Tenant outbox entries not yet delivered, including dead entries. |
| `p06_outbox_dead` | Tenant entries requiring controlled recovery. |

No tenant, customer, order or correlation ID is used as a metric label. HTTP counters reset when the process restarts; case and outbox gauges come from transactional storage. A storage-ready API can still have an unavailable worker. Alert on a growing received-case/outbox backlog as well as HTTP health.

## Verification scope

Run the operator/API suite with:

```bash
uv run --locked pytest tests/test_api.py -q
uv run --locked pytest tests/test_erp.py tests/test_review_regressions.py -q
node --check src/crm_workflow/static/app.js
```

The API suite uses the actual service and database with the explicitly synthetic CRM and ERP. It exercises duplicate intake, cross-tenant refusal, self-approval refusal, stale approval scope, the core execution/readback flow, later human-edit drift, signed webhook tampering, streamed size limits, error redaction and scoped metrics. The ERP suite runs the HTTPERP adapter against the actual ASGI service and a separate transactional store; it checks receipt replay and scope/expiry/CAS refusal without a local fallback. Review regressions cover compensated readback, foreign response rejection, unknown stock outcomes, approval/expiry races and bounded HTTP response consumption. These tests invoke service steps directly and do not stand in for the separately executed Temporal suite or real vendor acceptance. Browser screenshots, when supplied, must come from an actual run of this desk.

Implementation references: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), [FastAPI security dependencies](https://fastapi.tiangolo.com/reference/security/), [FastAPI lifespan testing](https://fastapi.tiangolo.com/advanced/testing-events/) and [Starlette ASGI middleware](https://www.starlette.io/middleware/). Dependency versions are resolved in `uv.lock`; the repository's execution evidence records the versions actually tested.
