# Acceptance and remaining work

## Delivery boundary

Local source delivery was merged to `main` through PR #2 after successful GitHub Actions PR CI run 43767041683 (attempt 2). The first post-merge run exposed a distinct browser-launch issue; see [CI evidence](evidence/ci-main-20261115.md). These facts are distinct from provider acceptance.

`0.1.0-rc.1` is an implemented and exercised local vertical slice with prepared provider integration. The complete P06 project is **not accepted** until an authorized Salesforce/MuleSoft run satisfies the original provider criteria. Issue #1 remains open. No skipped test, source parse, mock response, image build or checksum is used to close that gate.

## Requirement-to-evidence map

| Requirement | Implemented | Execution evidence and limit |
| --- | --- | --- |
| Typed intake, customer/order lookup, availability and proposal | Yes | Core and API tests; actual HTTP reference smoke with synthetic systems |
| Unknown/ambiguous/missing/contradictory request handling | Yes | Core negative tests; no identity or availability is guessed |
| Separate approver, scoped plan, expiry, immediate preconditions | Yes | Core/API tests, approval-expiry race regression, real Temporal approval wait |
| Actual durable business workflow | Yes | Real Temporal server, replay, abrupt process exit after CRM commit, persistent history restart |
| CRM change, ERP reservation and final reread | Yes | Synthetic reference smoke; HTTP ERP test uses a separate database |
| Duplicate delivery and immutable effect keys | Yes | Duplicate intake tests, real PostgreSQL concurrent intake, killed-worker recovery |
| Lost CRM or ERP response | Yes | Persistent synthetic effects plus actual Temporal retry/recovery; vendor path awaits live run |
| Safe compensation and later human edits | Yes | Conditional compensation, uncertain-stock refusal, compensation conflict and drift readback tests |
| Tenant separation and denied permissions | Yes at application/reference boundaries | API, ERP and misrouted readback tests; actual Salesforce permission refusal still required |
| Salesforce through MuleSoft | Source and adapter prepared; Mule package built | Actual Maven build for 4.9.24, bundled connector inventory and retained warnings; no Apex compile, Mule server execution/deployment or actual tenant call |
| n8n peripheral intake | Export and isolated runtime qualifier | Actual 2.47.5 import; missing/wrong inbound credentials return 403, valid trigger returns 202, duplicate maps to one case, distinct approval and Temporal completion/readback observed. Original export stays inactive and credential-free |
| Interchangeable intent interpreter | Rules and Ollama adapters | Rules and provenance policy tested; no local model inference run or quality benchmark claimed |
| Prompt injection in CRM notes | Canonical data boundary and authority separation | Synthetic malicious note rejected; model has no mutation/approval tools |
| OAuth expiry, 429, 5xx and timeout handling | Classifiers and bounded policies prepared | Local HTTP fault tests; Mule OAuth lifecycle, actual provider quotas and permission semantics unverified |
| Outbox, failure queue and controlled replay | Yes | Transaction rollback, duplicate dispatch, late failure-after-ACK and replay restrictions tested |
| Load and additional workers | Yes | Bounded local load with two separate workers; no provider throughput or HA claim |
| Restore | Yes for isolated data profile | Real PostgreSQL logical dump/restore and subsequent reconciliation; Temporal persistence restart tested separately |
| Container deployment | Reference Compose profile executed in GitHub Actions PR run | [PR run 43767041683 attempt 2](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43767041683/attempts/2) passed all three jobs, including Docker/HTTP smoke and Chrome. First `main` run 43768042601 passed Docker/smoke but failed Chromium launch; a corrected system-Chrome profile awaits new qualification. No real-provider deployment is implied |
| Operator browser rendering | Firefox and GitHub-hosted Chrome journey exercised | Actual Firefox results plus [successful PR CI Chrome journey](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43767041683/attempts/2). The first merged-main Chromium executable choice failed; the main fix must pass independently. |
| Monitoring and operational runbooks | Yes | Tenant-scoped API metrics tested; reference Prometheus/alerts prepared, on-call alert delivery unverified |
| Dependency, secret and licence checks | Yes | Locked Python dependencies, audit output, component metadata and source/history scan; no certification |
| Public source publication, licence and repository protections | Public + Apache-2.0 + application on `main` | [PR #2](https://github.com/mehdisafer/crm-order-workflow-agent/pull/2) merged on 15 November. The release-candidate tag is gated on a successful current-main CI; branch protection remains an owner-interface task. Provider acceptance remains separately open. |

## Original execution evidence

See [evidence/README.md](evidence/README.md) for original outputs, source identity and commands. Tests explicitly distinguish their synthetic systems, HTTP transports and real Temporal process. The PostgreSQL helper binary's version differs from the reference image and is identified in its record.

The load thresholds were declared before execution: 100% of 24 synthetic cases complete, zero duplicate effects, automatic p95 below 60 seconds, 120-second case deadline, zero provider calls. This is a bounded smoke-scale acceptance envelope for the isolated host. It is not a sales capacity target or a statement about Salesforce quotas.

## Open provider acceptance gate — P0

Required inputs are an existing authorized Salesforce sandbox or Developer Edition, effective API/Apex/custom-object access, dedicated Executor and Reader users, configured External Client Apps, an existing licensed Mule 4.9.24 / Java 17 runtime, trusted HTTPS and the exact nonproduction fixture scope. The application profile and ERP tenant/fixture must match.

With those inputs, run the checked-in install/preflight and bounded [real acceptance harness](vendor-integration.md). Retain the exact source commit, effective runtime/dependency versions, object descriptions, permission refusal, stale approval, actual lost-response receipt, immutable replay, final remote reads and Temporal histories. Investigate failures before repeating a write. Do not create a paid account or substitute a mock to mark this done.

## Remaining qualification and publication backlog

Apache-2.0 selection and the root `LICENSE` on `main` were completed via PR #4 on 15 November 2026. The original component and advisory inventories remain dated evidence; no current legal compatibility certification is implied.


| Priority | Work | Completion evidence |
| --- | --- | --- |
| P0 | Compile Apex and deploy actual Salesforce/Mule components | Mule packaging is observed; remaining evidence is successful Apex tests, actual server startup/deployment and effective identity/scope output |
| P0 | Execute complete real provider scenario and original acceptance faults | One real business result, correctly invalidated approval, actual permission denial, response-loss recovery without a duplicate |
| P1 | Qualify OAuth refresh, provider 429/timeouts and shared call budgets | Observed attempts and provider quota values, with the documented global bound respected |
| P1 | Finish merged-main Chrome CI regression qualification | PR run 43767041683 succeeded after public runner allocation; first main run 43768042601 failed at Chromium launch. Corrected system-Chrome + full UI exercise must pass on the release commit. |
| P1 | Rehearse recovery on the chosen operational platform | PostgreSQL backup, compatible Temporal history, provider reconciliation and measured RPO/RTO |
| P1 | Finalize tagged local RC, branch protection and anonymous access check | Public, About and Apache-2.0 are observed; code merged into `main`. Create the prerelease only after passing current-main CI; protect `main` through owner interface and confirm anonymous access. |
| P2 | Evaluate an explicitly supplied local model | Structured extraction accuracy, abstention, latency and observed resources on a labelled synthetic set |
| P2 | Extend to another approved business operation or source mapping | Versioned contract, reviewed field mapping, new policy and end-to-end evidence |

New business operations are additions to this delivered delivery-date slice. Provider acceptance is part of the existing scope, not an optional enhancement.

The n8n local trigger milestone was closed by original runtime evidence on 14 November 2026. Deploying that trigger on the eventual operational platform remains part of its separate deployment/recovery qualification. The initial registration and proxy-routing failures are retained alongside the passing run.

Public source publication was explicitly authorized on 14 November 2026. The maintainer handles operations that require the GitHub interface; account sign-in through an automated browser is not needed. Publishing the source with its documented limits is distinct from closing the original actual-provider acceptance gate. The concrete publication sequence and default-branch limitation are in [publication.md](publication.md).
