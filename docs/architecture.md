# Architecture and engineering decisions

## Product boundary

The first vertical slice changes a delivery date and reserves the existing order quantity. The SKU, customer, quantity and commercial terms are never model-controlled mutation fields. Requests for refunds, discounts, cancellations or another unsupported operation require clarification. No real customer notification is sent; the result event is delivered to a local audit sink and shown in the operator view.

The nominal workflow is intake → normalization → customer/order lookup → availability → typed plan → separate approval → CRM effect → ERP reservation → remote reread → result event. Every step uses a stable case/correlation ID. CRM notes are outside the canonical order contract and are never sent to a model.

## State and transaction model

`cases` stores the authenticated tenant, request identity, immutable intake digest, current projection, revision and global API-call count. `case_events` records structured transitions. `effects` records each write intent **before** a call, including its payload hash and attempts. `outbox` stores start, decision and result commands in the same transaction as the corresponding business transition. Foreign keys retain the relationship between the case, events, effects and outbox.

The source APIs have separate effect records: Salesforce's custom ledger is committed atomically with the order change; the original ERP's reservation is committed atomically with the stock decrement. A local effect-journal row does not prove that a remote write happened. `APPLIED` is assigned only after an effect receipt is validated. `UNKNOWN` remains visible across worker crashes.

An effect key is bound to its original case, system, operation and canonical request hash. The local journal only promotes a `PREPARED` or `UNKNOWN` intent when a verified remote receipt arrives. An identical repeated observation is a no-op, including its audit event; an incompatible receipt or a callback trying to rewrite `APPLIED`, `COMPENSATED` or `REJECTED` is refused and must be reconciled instead. The guarded update prevents a stale local observation from silently replacing a newer journal state. These source-level protections do not substitute for the provider's own transactional idempotency guarantees.

| Boundary | Atomic invariant | Failure outside the boundary |
| --- | --- | --- |
| Intake database transaction | Case plus accepted event plus `workflow.start` outbox | Dispatcher retries the same workflow ID |
| Approval database transaction | Exact plan decision plus `workflow.decision` outbox | Signal may be duplicated; it grants no permission |
| Salesforce transaction | Revision check plus order change plus immutable effect | Read effect and order before repeating |
| ERP transaction | Revision/quantity check plus reservation | Reconcile reservation before compensation |
| Final database transaction | Observed readback plus result event | Local notification dispatch may be repeated safely |

No distributed transaction spans these systems. The explicit saga preserves partial effects and defines when compensation is allowed.

## Approval authority

Server-owned credentials map to a stable actor, tenant and roles. Request bodies cannot supply an actor or privileges. A requester cannot approve their own case, even if an administrative configuration assigned both roles. The application approver and provider executor are separate responsibilities. The worker is the only mutation path exposed by the application architecture; the operator API has no arbitrary execution endpoint.

The canonical plan hash covers case, requester, tenant, customer identity, order identity and state, allowed fields, requested date, stock revision/quantity, risk, compensation permission, policy version and absolute expiry. Approval validates that exact hash. New effects reload and validate the stored decision and current preconditions. A receipt can still be reconciled after expiry, but expiry never authorizes a new mutation.

The database transition checks the deadline after acquiring the row lock. If approval races the Temporal expiry activity, the activity rereads a committed decision rather than marking an approved case failed. Case transitions compare revisions and tolerate an overlapping activity that has already advanced the state. API attempts to approve a stale state still return a conflict.

Static bearer principals are a deliberately small private-reference identity mechanism. Rotating or revoking their external configuration requires a controlled service reload. A production identity provider, SSO lifecycle and operational access reviews are not claimed by this profile.

## Retry ownership and unknown outcomes

Temporal activities own business retry scheduling. Workflow code is deterministic and records only the case ID, bounded execution settings, state and approval deadline in history. Names, request text, CRM notes and tokens do not belong in activity results.

The HTTP adapters issue one attempt and cap the streamed response. Transport failures during writes are unknown outcomes. Status 429 and 5xx are classified for bounded recovery, and `Retry-After` delays are retained. The persistent API-call budget and write-attempt budget survive worker replacement. Database-backed system admission and circuit state are shared across workers; leases expire after bounded activity lifetimes.

The n8n export disables retries and requires stable source message IDs. Mule contains no second saga. Its effective HTTP and OAuth retry settings must be verified at deployment; see the vendor runbook for the explicitly bounded OAuth 401 exception. A transport-level retry still uses the exact original effect key and approved body.

| Write | Stable key | Real deduplication mechanism | Reconciliation |
| --- | --- | --- | --- |
| CRM date | `case-id:crm` | Salesforce unique external ledger key, request digest and order lock | GET effect, validate before/after, GET current order |
| ERP reservation | `case-id:stock` | Reservation primary key, payload digest and conditional stock update | GET reservation, validate tenant/order/SKU/quantity/plan |
| CRM compensation | `case-id:crm:compensate` | Separate effect key, original effect binding and exact current revision | GET compensation effect and current order |

If a stock write is still `UNKNOWN` and its receipt is absent, the workflow escalates. It does not restore the CRM date while a reservation may still commit. A definitive first-attempt remote refusal can be recorded as `REJECTED`; it cannot erase uncertainty from an earlier timed-out attempt.

## Compensation and reporting

Compensation is a new conditional effect, with its own key and retained evidence. It restores only the date in the original before-state. A newer human revision, a changed customer/scope, expired authority or unresolved reservation prevents it. The application does not claim a universal rollback.

Completion requires observed CRM and ERP state. A subsequent operator reconciliation preserves the historical workflow outcome and separately reports current drift. For a compensated case the expected state is the compensation's after-state **and no reservation**. Misrouted provider objects are rejected before storing them in a tenant's reconciliation view.

## Interpreters and metadata

`RulesProposer` accepts explicit structured fields and a small documented reference/date grammar. `OllamaProposer` implements the same typed interface using structured output and a 256-token generation cap. Neither receives mutable tool handles or approval APIs. External model transmission is disabled by default and requires an explicit configuration override. Only request fields are sent; provider notes, credentials and customer names are omitted.

Configuration is parsed with safe YAML and a strict Pydantic schema. Profiles select reviewed adapters and known operations. Versioned source mappings live in the canonical system API contracts and Salesforce field metadata. Adding a different mapping or mutation requires a reviewed contract/code change; no metadata evaluates SQL, Python, expressions or arbitrary endpoints. This keeps the present single Salesforce mapping explicit. A self-service mapper for arbitrary CRMs is outside this first slice.

## Deployment decisions

The deployment reference uses one private host, PostgreSQL, a persistent single-node Temporal development service, an API and bounded worker processes. Docker Compose owns those resources. A real deployment with stronger availability targets must replace the development server with an operated Temporal service and qualify the supported database/runtime combination.

No cloud account, resource group, managed tenant or paid target was supplied. Terraform would have no authorized external resource to own in this delivery. Adding a second owner for the same Compose volumes or a fictitious cloud module would introduce drift. Terraform is reserved for the selected, actually supported target when that target is authorized. Kubernetes and a second cloud are not prerequisites for this business slice.

The reference image, Compose stack, vendor build and real integration have separate evidence statuses. An image that builds is not a deployed API; a service that starts is not business acceptance. The isolated PostgreSQL restore exercise used the available helper binary version recorded in evidence, not the reference container's version.

## Sources

- [Temporal activity retry policies](https://docs.temporal.io/encyclopedia/retry-policies) and [Python testing environment](https://python.temporal.io/temporalio.testing.WorkflowEnvironment.html).
- [SQLAlchemy version checks](https://docs.sqlalchemy.org/en/20/orm/versioning.html) and [SQLAlchemy 2.1 release notes](https://docs.sqlalchemy.org/en/21/changelog/changelog_21.html).
- [FastAPI bearer authentication](https://fastapi.tiangolo.com/reference/security/) and [release notes](https://fastapi.tiangolo.com/release-notes/).
- [uv locking and synchronization](https://docs.astral.sh/uv/concepts/projects/sync/).
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs).
- [PostgreSQL backup and restore](https://www.postgresql.org/docs/current/backup.html).
- [Provider versions, permission semantics and licensing references](vendor-sources.md).
