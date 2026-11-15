# Salesforce, MuleSoft and n8n installation and qualification

## Current status

The repository contains original Salesforce metadata and Apex, a Mule application, a RAML system API contract, a credential-free n8n workflow, and a bounded real-vendor qualification harness. **Mule Maven packaging succeeded on 14 November 2026**, with the configured 4.9.24 target and Java 17. The original output, unresolved configuration warnings, archive inventory and dependency tree are retained in [the packaging evidence](evidence/mule-build-20261114/README.md).

An isolated official **n8n 2.47.5** instance also imported and executed the trigger against the local API, real Temporal and synthetic CRM/HTTP ERP. Missing/wrong inbound credentials returned 403; the valid trigger returned 202, duplicate delivery preserved one case, and separate approval led to a completed workflow and matching readback. [The n8n qualification](../integrations/n8n/README.md) identifies the exact source and retained failures.

**No authorized Salesforce org or running MuleSoft server was supplied. Salesforce compilation, Apex tests and Mule runtime/deployment remain unverified.** A successful package build does not establish runtime configuration, authentication, remote permissions or business effects against those providers.

The runnable local profile uses explicitly identified synthetic services. It is useful for the business demonstration and recovery tests; it does not satisfy the Salesforce/MuleSoft acceptance gate.

## Responsibility and trust boundaries

| Component | Authority | Excluded responsibility |
| --- | --- | --- |
| n8n | Authenticate an intake trigger and submit the source `message_id` | Approval, business retries, saga state, CRM mutations |
| Operator API and transactional store | Resolve application actors and tenants; retain requests, decisions, effects and outbox records | Treating a received signal as authorization |
| Temporal | Execute and resume the business saga using durable history | Inventing permissions or stock |
| MuleSoft system API | Authenticate one technical client, bind its tenant, expose a small API, acquire Salesforce OAuth tokens | Parallel saga, automatic 5xx retry, arbitrary Salesforce endpoint proxy |
| Salesforce Apex | Enforce the actual Salesforce user's permissions and sharing; atomically compare revision, change a date and record the effect | Approving its own business plan |
| Synthetic ERP system API | Compare the approved stock revision and reserve inventory idempotently | Pretending to be a licensed commercial ERP |

The executor's Salesforce identity is bound to `User.P06_Tenant__c`. The application principal and Mule configuration are also tenant-bound. A supplied `tenant_id` is a constraint, never a grant of access. Only `/v1/capabilities` may omit it, because that response derives scope from the technical identity.

### Why dedicated Salesforce objects

`P06_Order__c` is a portfolio-specific custom object holding synthetic orders. `P06_Effect__c` is its immutable effect ledger. Customers use standard `Account`, with two custom scope/reference fields. This is a real Salesforce integration when deployed; it makes **no claim about standard Salesforce Order, Commerce, CPQ, inventory or edition entitlement**. Installation must verify that the authorized org supports the custom objects, Apex, API access and required identities.

The permission sets do not grant View All, Modify All, record deletion, user administration, arbitrary order creation or arbitrary order-field changes. Objects use private sharing. A technical executor must own or receive explicit access to the fixture records. Its user tenant field is read-only. A separate reader identity is needed to exercise the Salesforce refusal; passing an override header is not an alternative identity.

## Pinned implementation targets

Versions were checked against the official references in [vendor-sources.md](vendor-sources.md) on 13 November 2026.

| Component | Source/configuration target | Verification in this environment |
| --- | --- | --- |
| Salesforce metadata and Apex | API 65.0, explicit `WITH USER_MODE` / user-mode DML | Source review and XML parse; no org compilation |
| Mule runtime | 4.9.24, Java 17 | Explicit packaging target and generated descriptor; no server execution |
| Mule Maven plugin | 4.10.4, Maven 3.9–3.10 | Package build succeeded with Maven 3.10.0 / Corretto 17.0.21, with retained warnings |
| HTTP connector | 1.12.2 | Exact JAR resolved and included in the generated archive; runtime unverified |
| OAuth module | 1.1.30 | Exact JAR resolved and included in the generated archive; token lifecycle unverified |
| n8n | 2.47.5 | Actual import and authenticated trigger-to-Temporal completion observed in an isolated synthetic profile; operational deployment unverified |

Direct Maven dependencies and the plugin are pinned. The successful build has a retained dependency tree and an inventory of the JARs actually bundled in the archive. This is observed dependency evidence, not a comprehensive SBOM or vulnerability assessment. Runtime, connectors, SaaS access and n8n keep their own licensing terms. No vendor binary or license file is redistributed by this repository. The repository's own license remains a separate maintainer decision.

## Install into an already authorized environment

### 1. Verify the Salesforce target

Use an existing, explicitly authorized sandbox or Developer Edition org. Do not create a paid account or change org settings to conceal a missing prerequisite. Authenticate the Salesforce CLI outside this repository. Do not save or print access tokens in installation evidence.

From the repository root:

```bash
integrations/salesforce/scripts/deploy.sh YOUR_EXPLICIT_DEMO_ALIAS --check-only
```

The script queries `Organization.IsSandbox` and `OrganizationType`, then performs a dry-run deployment with local Apex tests. It refuses an unrecognized production org. It contains no destructive metadata and does not select a default org.

Inspect the validation result before the actual installation:

```bash
integrations/salesforce/scripts/deploy.sh YOUR_EXPLICIT_DEMO_ALIAS --execute
```

These commands are provided for the authorized operator; they were **not executed against an org** here. The Apex tests require the standard `Minimum Access - Salesforce` profile. If that profile is absent or incompatible with the tenant, prepare an explicitly reviewed least-privilege fixture profile and update the test setup. Never replace it silently with a System Administrator profile.

### 2. Provision identities and synthetic records

An org administrator must:

1. Assign `P06_Executor` to the dedicated executor and `P06_Reader` to a separate reader. Both users must have the API capability required by the org's license.
2. Set each user's `P06_Tenant__c` to the fixture tenant, for example `demo-industrial`. Do not grant either user permission to modify this field.
3. Seed a synthetic Account and order owned by the executor. The shared fixture is tenant `demo-industrial`, customer reference `CUST-001`, order reference `ORD-1001`, SKU `SKU-001`, quantity `10`; these values align with the synthetic ERP dataset. `integrations/salesforce/scripts/seed.apex.example` is an explicit template with a required executor username; it refuses to insert a duplicate known seed.
4. Share the synthetic Account and order with the reader as read-only. Do not broaden organization-wide sharing. The ledger remains owned by the executor.
5. Configure separate External Client Apps with `client_credentials`, API scope, administrator-approved access and each corresponding run-as user. `external-client-app.requirements.json` records the required policy. Client secrets and app policies containing actual user identities stay outside Git.

Salesforce restricts new Connected App creation from Spring 2026; this procedure uses External Client Apps. An existing Connected App can be used only if the authorized administrator verifies its effective policy. No new connection type, billing change or account is created automatically.

A reader is not an approver. Application requester/approver/operator credentials remain separate from provider executor credentials. The workflow reloads the stored approval before every new effect.

### 3. Package and install MuleSoft

Packaging is an independently executable check: it needs Java 17, Maven 3.9.0–3.10.0 and access to the declared artifacts. It does not require a running Salesforce org or a deployed Mule server. Deployment and live provider qualification have additional prerequisites below. Keep artifact repository credentials outside the POM.

The POM explicitly passes `mule.runtime.version` into the plugin's `runtimeVersion` setting. Declaring a property or `minMuleVersion` alone does not select the Mule framework used during packaging. The public dependency repositories are Anypoint Exchange v3, MuleSoft Releases and MuleSoft Public, following the [official Mule 4.9 Maven reference](https://docs.mulesoft.com/mule-runtime/4.9/maven-reference). Successful resolution of the complete dependency graph must still be observed. A protected enterprise artifact requires existing authorized access; adding a repository URL does not grant that access.

With `JAVA_HOME` and `PATH` selecting the reviewed Java 17/Maven installations, run from the repository root:

```bash
mvn --batch-mode --no-transfer-progress -f integrations/mulesoft/pom.xml \
  -DP06_RUNTIME_CONFIG="$PWD/integrations/mulesoft/runtime.yaml.example" \
  clean package
mvn -f integrations/mulesoft/pom.xml dependency:tree -DoutputFile=target/dependency-tree.txt
```

The example configuration contains property names without provider credentials. Supplying its path does not prove that the Maven parser or runtime resolves the external configuration: the observed build retained warnings for `${P06_RUNTIME_CONFIG}` and `${gateway.tlsKeyStore}`. It also skipped unconsumed-stream validation because its configuration/metadata services were unavailable. These warnings were preserved; no artificial configuration, private key or credential was bundled to suppress them. Use the protected deployment configuration for runtime startup and verify those settings in the actual server. `-DlightweightPackage` produces a source archive without the dependencies needed for deployment and does not satisfy the package-build gate.

Record the full packaging result, source digests, JDK/Maven versions and dependency inventory with the delivered commit. A package build does not prove deployed connector behavior. The 13 November delivery had no Maven or Salesforce CLI and only Java 21. On 14 November, an isolated Maven 3.10.0 and Amazon Corretto 17.0.21 were acquired from their official public distributions with verified SHA-512 and SHA-256 checksums respectively. Maven reported `BUILD SUCCESS` in 3 minutes 24 seconds. The archive contains a generated Mule AST and 12 bundled JARs. The first dependency-tree command failed after reusing an expired executor proxy; its original failure and the successful rerun with the current configured proxy are both retained. See [the complete evidence and limits](evidence/mule-build-20261114/README.md). Live Salesforce/MuleSoft acceptance remains open.

Copy `integrations/mulesoft/runtime.yaml.example` to a protected file **outside the checkout**. Provide its path as `P06_RUNTIME_CONFIG`. Supply a PKCS#12 HTTPS server certificate/private key, a random gateway bearer token, the exact Salesforce My Domain host, OAuth token endpoint and client credentials. Use private routing. The sample binds to loopback and cannot authenticate with empty secrets. A second instance using the reader's Salesforce app is required for permission testing.

Install the produced application archive into the existing licensed runtime through its authorized deployment mechanism. For the standalone reference profile, set `P06_MULE_HOME` to that existing runtime, `JAVA_HOME` to the reviewed Java 17 installation, and `P06_RUNTIME_CONFIG` to the protected external configuration. Start it with:

```bash
integrations/mulesoft/scripts/launch.sh console
```

The exact server distribution remains a separate access gate. On 14 November 2026, the official standalone/patching documentation directed Enterprise distributions to the customer portal or account representative; the anonymous public Kernel catalog did not list 4.9.24 and its exact ZIP path returned 404. No anonymous exact-version server distribution was established, and no other version was substituted. Supply an authorized 4.9.24 distribution with applicable usage rights before this startup step; see the [bounded access-check evidence and primary sources](evidence/mule-build-20261114/README.md#exact-server-access-check--14-november-2026).

The launcher sets real JVM arguments `-M-Dmule.http.client.maxRetries=0` and `-M-Dmule.http.client.retryOnAllMethods=false`. These are not YAML application settings. It also passes the external configuration path as a JVM property and refuses a non-Java-17 installation. Existing wrapper or service configuration can still introduce conflicting JVM flags, so inspect the **running** selected process before qualification:

```bash
python integrations/mulesoft/scripts/verify_runtime.py --pid YOUR_EXPLICIT_MULE_JAVA_PID
```

The verifier uses `jcmd` for that one PID and emits only the two retry properties, Java specification version and boolean configuration checks. It never prints or persists the full system-property output, which may contain secrets. A nonzero result blocks runtime qualification. Capture its report separately for both executor and reader runtimes. This check proves observed property values, not connector retry behavior; a controlled remotely-closed test and effective request counts remain part of the first live runtime qualification.

This repository does not provision CloudHub, start a subscription, redistribute Mule runtime, or expose the API publicly. The runtime/deployment mechanism is a supplied environment prerequisite, not an assumed cloud resource.

#### Retry and timeout budget

Temporal owns business retries. n8n and the Python HTTP adapter do not retry calls. Mule has no `until-successful` scope and no independent saga. The HTTP connector otherwise retries idempotent methods three times on a remotely closed connection; the standalone launcher disables that built-in behavior with the JVM properties above. Confirm the effective properties before claiming a bounded provider attempt budget. The one deliberate transport-level exception is the OAuth module's refresh behavior: a **401** can refresh the token and retry the callback. A **403** must remain a permission refusal, not trigger refresh. This is configured explicitly because the OAuth module's default includes both statuses.

The application must count this possible additional callback when budgeting provider quotas. A retried POST preserves the exact immutable effect payload and key. It is safe only because the actual Apex endpoint implements the ledger and conditional write; the HTTP header or key alone proves nothing.

The sample permits four active Mule requests/connections and a ten-second API response timeout. OAuth 1.1.30 bounds token/refresh requests at sixty seconds. A shorter application timeout can therefore end while Mule is still acquiring credentials or waiting for Salesforce. Such a write is **uncertain**. The workflow must reconcile, and later attempts must retain the same key and approved payload. The live test must measure actual timeout behavior and quotas before changing limits.

### 4. Verify capabilities without mutation

Set these values in a protected environment:

- `P06_SF_INSTANCE_URL` and `P06_SF_ACCESS_TOKEN`: authorized Salesforce origin and a short-lived token.
- `P06_MULE_URL`, `P06_MULE_TOKEN`: deployed gateway endpoint and its tenant-bound bearer token.
- `P06_TENANT`: the assigned synthetic tenant.

Then run:

```bash
python integrations/salesforce/scripts/preflight.py
```

The command describes the actual objects and required fields and reads the Salesforce capability endpoint through MuleSoft. It emits only the required capability subset and effective create/update flags. Missing credentials return `BLOCKED` with exit code 2. Readable metadata is not evidence of a successful mutation or a successful rights refusal. This remote preflight cannot inspect a Mule JVM: it explicitly reports `mule_jvm_retry_properties: NOT_OBSERVED` until the separate runtime-properties evidence is captured and reviewed.

Set the application's real profile with `P06_PROFILE=salesforce`, `P06_MULE_URL`, `P06_MULE_TOKEN`, and the configured synthetic ERP endpoint/token. `P06_MULE_CA_FILE` may reference a reviewed CA bundle for private HTTPS. Certificate verification must stay enabled. The adapter has no automatic fallback to synthetic CRM.

### 5. Import the n8n trigger

Import `integrations/n8n/order-intake.workflow.json` into the authorized n8n instance. It is inactive and contains no credential IDs, credential values or pinned execution data. Bind two independently stored Header Auth credentials:

| Node | Credential purpose |
| --- | --- |
| Authenticated intake | Validate an inbound `X-P06-Intake-Key` header |
| Submit once to workflow authority | Add `Authorization: Bearer …` for an application principal with requester role only |

The destination is a trusted literal URL, defaulting to `http://api:8000/api/v1/cases` on the private Compose network. Replace it only with the intended application endpoint. Do not derive destinations from request data. Input matches the versioned `OrderRequest` contract. The source must provide a stable `message_id`; do not generate a new ID on retry.

The workflow returns the actual HTTP intake response. It contains no approval, CRM write, client email or business retry. Execution persistence is disabled in the export to avoid retaining authentication headers; the application stores the useful correlation and audit data. Configure an external persistent n8n encryption key, keep user management enabled, and restrict editor access. Importing the workflow does not activate it or prove the trigger works.

## What the Salesforce endpoint guarantees by design

`POST /v1/orders/{orderId}/effects` accepts exactly the typed `Change` body in the RAML contract. Only delivery-date changes and their explicitly referenced compensations are supported. Extra fields are rejected by strict JSON deserialization.

For a new write, Apex checks the running identity/tenant, custom execute permission, actual object/field permissions, order/customer relationship, expiration and expected revision. It takes a row lock, then checks the effect ledger again. The order change and effect insert share one transaction. Every caught write failure rolls back to the savepoint; a permission refusal before that point has not written any placeholder or consumed an effect key.

The ledger's unique external key is a SHA-256 digest of the JSON array `[tenant, effect_key]`, so colons inside either identifier cannot create an ambiguous namespace. The initial unexecuted draft used delimiter concatenation; no deployed ledger was migrated in this delivery. It also stores a digest of the immutable request. Reusing a key with changed scope or body returns a conflict. An exact replay returns the retained result without incrementing the order revision. An expired exact replay may still retrieve existing evidence, but an expired new request cannot create an effect.

A trigger increments the revision for every order update, including a human change. Technical executor updates that bypass the effect endpoint are rejected. Ledger insertion is allowed only while the handler is applying an effect; subsequent updates/deletions are rejected. A compensation must reference the original forward effect, retain its approved plan hash, match the original after-revision/date and restore precisely the original before-date. Newer state causes a visible conflict. Expired compensation authority does not become implicit permission to restore an old value.

These are implementation properties pending real org compilation and execution. They are not a promise of Salesforce permissions, isolation or deduplication based on local tests.

## Run the real acceptance scenarios

`integrations/vendor_validation/live_acceptance.py` exercises the running operator API and real Temporal service. It does not call workflow methods directly or instantiate a synthetic CRM adapter. Preconditions are an API/worker in the real profile, a separate approver, configured synthetic ERP stock, both deployed Mule identities, and an HTTPS fault proxy in front of the executor gateway.

The fault proxy forwards a real request to real MuleSoft, waits for a real successful Salesforce response, persists the received evidence, and closes the local response socket once. It never fabricates a write. Its location is explicitly recorded as **after the real upstream response**. If an upstream write itself becomes uncertain, the proxy does not automatically forward a second write while that effect is in flight.

Start a one-shot proxy on the same isolated host as the worker. Supply a trusted certificate and private key outside Git; there is no insecure TLS bypass. Provide `P06_MULE_DIRECT_URL`, a separate `P06_FAULT_CONTROL_TOKEN` and `P06_LIVE_SCOPE=synthetic_nonproduction` in the protected environment:

```bash
uv run python integrations/vendor_validation/fault_proxy.py \
  --cert /run/secrets/p06-fault-proxy.crt \
  --key /run/secrets/p06-fault-proxy.key \
  --receipt .local/vendor-run/response-drop.json
```

Configure the worker's `P06_MULE_URL` to the trusted HTTPS proxy address and its `P06_MULE_CA_FILE` if needed. The proxy listens only on `127.0.0.1:9443`. Use `--upstream-ca` when Mule uses a private CA. The core API can remain on its private interface; no business service needs public exposure.

Supply the following harness variables from the protected environment: `P06_API_URL`, `P06_REQUESTER_TOKEN`, `P06_APPROVER_TOKEN`, `P06_OPERATOR_TOKEN`, `P06_MULE_DIRECT_URL`, `P06_MULE_TOKEN`, `P06_MULE_READER_URL`, `P06_MULE_READER_TOKEN`, `P06_FAULT_URL`, `P06_FAULT_CONTROL_TOKEN`, `P06_TEMPORAL_ADDRESS`, `P06_TEMPORAL_NAMESPACE` if not `default`, `P06_TENANT`, `P06_CUSTOMER_REFERENCE` and `P06_ORDER_REFERENCE`. `P06_CA_FILE` can contain the reviewed CA certificates needed by the harness. Use an order whose current requested date differs from today plus ten days and enough synthetic stock for one reservation.

```bash
uv run python integrations/vendor_validation/live_acceptance.py \
  --execute --max-seconds 240 --output .local/vendor-run/acceptance
```

The output directory must be new. `--max-seconds` is one absolute budget measured from command entry, covering capability probes, both preparation waits, execution and Temporal history collection. Every HTTP call, complete response stream, RPC and poll is clamped to the remaining budget; phases do not reset the clock. The harness records each original message ID before submission and case IDs immediately after receipt, then retains them in its final report on timeout. An interrupted run must be reconciled using those identities instead of resubmitted with new ones. It submits two cases and checks:

1. Duplicate intake returns the same case.
2. The first case passes separate approval, the real dropped-response fault, ledger reconciliation, ERP reservation and final readback.
3. Replaying the exact committed body against real Salesforce changes no state and increments no revision.
4. The separately provisioned Salesforce reader refuses the same already committed request with `permission_denied`; this avoids creating another mutation if that reader is unexpectedly overprivileged.
5. The second case approves a previously observed snapshot and is invalidated after the first case changed CRM/stock. No second effect may exist.
6. Operator reconciliation matches observed Salesforce and ERP state. Actual Temporal histories and run IDs are collected for both cases.

A successful report says `EXECUTED_CHECKS_PASSED`, not that the entire project is accepted. Review source commit, dirty-worktree flag, original inputs, source versions, fault location and histories. Worker-crash recovery, compensation conflict, OAuth expiration, actual 429 quotas, restoration, n8n operation and the remaining acceptance scope require their own evidence. No provider load test is included; the harness is deliberately bounded to the synthetic fixture.

## Reconciliation, rollback and operations

After any unknown POST outcome, read `/v1/effects/{effectKey}` and then `/v1/orders/{orderId}`. Compare the exact approved scope, before/after values, revision and plan hash with the retained request. A missing ledger row while a request may still be running is not proof that no mutation will occur. Do not invent a new key. Preserve the case and escalate if the result cannot be established.

For a failed compensation, retain both the original effect and current state. Do not edit or delete the immutable ledger, overwrite a human change, or turn the old date into an unconditional patch.

Rollback of application source is a controlled deployment of a compatible previous version. No destructive schema rollback is supplied. Export and verify the synthetic objects/effects before schema changes, preserve the transaction database/outbox and Temporal history, and rehearse restore separately. No Salesforce restore exercise was performed in this environment.

Operational evidence must redact credentials and real personal data. The Mule logger emits correlation, status and integration type only; HTTP wire logging is disabled. CLI access-token output, n8n editor execution headers and OAuth diagnostics must not be committed. Capture actual license, permission, quota and runtime findings in the open provider milestone before calling the integration accepted.
