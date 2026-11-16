# Acceptance and remaining work

## Delivery boundary

Public local V1 was delivered through [PR #2](https://github.com/mehdisafer/crm-order-workflow-agent/pull/2) and its Chrome/mobile corrections through [PR #7](https://github.com/mehdisafer/crm-order-workflow-agent/pull/7). The immutable [pre-release `v0.1.0-rc.1`](https://github.com/mehdisafer/crm-order-workflow-agent/releases/tag/v0.1.0-rc.1) points to `cdf3c0e`, whose [main CI 43770254516](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43770254516) passed all three required jobs. Test-only [PR #9](https://github.com/mehdisafer/crm-order-workflow-agent/pull/9) later extended Temporal/CircleCI coverage; [main CI 43772725456](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43772725456) on `4dc6e2a` also passed all three jobs. That later result does not requalify or move the earlier immutable release tag.

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
| Container deployment | Executed and qualified on hosted `main` reference CI | [Release SHA CI 43770254516](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43770254516) and [post-release CI 43772725456](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43772725456) both passed Docker, PostgreSQL/HTTP ERP/Temporal, synthetic readback and Chrome reference journey. No real-provider deployment is implied. |
| Operator browser rendering | Actual Firefox and hosted Chrome exercised | The release-source and post-release `main` runs produced six actual desktop/mobile captures with independent approval, matching readback, zero relevant browser errors and no horizontal overflow. Earlier Chromium launch and fixture failures remain historical evidence. |
| Monitoring and operational runbooks | Yes | Tenant-scoped API metrics tested; reference Prometheus/alerts prepared, on-call alert delivery unverified |
| Dependency, secret and licence checks | Yes | Locked Python dependencies, audit output, component metadata and source/history scan; no certification |
| Public source publication, licence and repository protections | Public, Apache-2.0, application on `main` and tagged local RC | GitHub confirms [actual `v0.1.0-rc.1` prerelease](https://github.com/mehdisafer/crm-order-workflow-agent/releases/tag/v0.1.0-rc.1), bound to original passing CI SHA. Owner-supported branch protection and independent signed-out navigation remain outstanding; Salesforce/MuleSoft provider acceptance is open. |

## Original execution evidence

See [evidence/README.md](evidence/README.md) for original outputs, source identity and commands. Tests explicitly distinguish their synthetic systems, HTTP transports and real Temporal process. The PostgreSQL helper binary's version differs from the reference image and is identified in its record.

The load thresholds were declared before execution: 100% of 24 synthetic cases complete, zero duplicate effects, automatic p95 below 60 seconds, 120-second case deadline, zero provider calls. This is a bounded smoke-scale acceptance envelope for the isolated host. It is not a sales capacity target or a statement about Salesforce quotas.

## Open provider acceptance gate — P0

Required inputs are an existing authorized Salesforce sandbox or Developer Edition, effective API/Apex/custom-object access, dedicated Executor and Reader users, configured External Client Apps, an existing licensed Mule 4.9.24 / Java 17 runtime, trusted HTTPS and the exact nonproduction fixture scope. The application profile and ERP tenant/fixture must match.

With those inputs, run the checked-in install/preflight and bounded [real acceptance harness](vendor-integration.md). Retain the exact source commit, effective runtime/dependency versions, object descriptions, permission refusal, stale approval, actual lost-response receipt, immutable replay, final remote reads and Temporal histories. Investigate failures before repeating a write. Do not create a paid account or substitute a mock to mark this done.

## Remaining qualification and publication backlog

Apache-2.0 and the root `LICENSE` were completed through PR #4, and the public local release is tagged. Original advisory inventories remain historical, not legal/security certification. Post-release PR #9 increased the real Temporal recovery profile from 10 to 12 tests without changing the tagged source or production logic.


| Priority | Work | Completion evidence |
| --- | --- | --- |
| P0 | Compile Apex and deploy actual Salesforce/Mule components | Mule packaging is observed; remaining evidence is successful Apex tests, actual server startup/deployment and effective identity/scope output |
| P0 | Execute complete real provider scenario and original acceptance faults | One real business result, correctly invalidated approval, actual permission denial, response-loss recovery without a duplicate |
| P1 | Qualify OAuth refresh, provider 429/timeouts and shared call budgets | Observed attempts and provider quota values, with the documented global bound respected |

| P1 | Rehearse recovery on the chosen operational platform | PostgreSQL backup, compatible Temporal history, provider reconciliation and measured RPO/RTO |
| P1 | Verify signed-out public access, private reporting and continued check enforcement | **`main` protection is observed:** active `main-protection-v1` ruleset (16 Nov 2026), PR-only changes, deletion/force-push prohibited and four required CI contexts; zero approvals currently required. A separate signed-out HTTP/browser check remains unverified, and private vulnerability reporting must still be confirmed in owner settings. |
| P2 | Evaluate an explicitly supplied local model | Structured extraction accuracy, abstention, latency and observed resources on a labelled synthetic set |
| P2 | Extend to another approved business operation or source mapping | Versioned contract, reviewed field mapping, new policy and end-to-end evidence |

New business operations are additions to this delivered delivery-date slice. Provider acceptance is part of the existing scope, not an optional enhancement.

The n8n local trigger milestone was closed by original runtime evidence on 14 November 2026. Deploying that trigger on the eventual operational platform remains part of its separate deployment/recovery qualification. The initial registration and proxy-routing failures are retained alongside the passing run.

Public source publication was explicitly authorized on 14 November 2026. The maintainer handles operations that require the GitHub interface; account sign-in through an automated browser is not needed. Publishing the source with its documented limits is distinct from closing the original actual-provider acceptance gate. The concrete publication sequence and default-branch limitation are in [publication.md](publication.md).
