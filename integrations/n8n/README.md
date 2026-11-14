# n8n intake workflow

Import `order-intake.workflow.json` into the authorized n8n instance, then bind the two Header Auth credentials in the editor. The workflow is inactive and contains no credential values or IDs. It forwards a stable source `message_id` to the application's requester API and returns its intake receipt. Temporal owns the durable workflow.

Bind the inbound credential to `X-P06-Intake-Key`. Bind the outbound credential to `Authorization: Bearer <requester token>` and set the literal API URL for the authorized environment. Publish the imported workflow through n8n after these bindings are reviewed. Approval belongs to a different application identity; this trigger has no approval credential.

## Observed local qualification

On 2026-11-14, the official **n8n 2.47.5 npm distribution** ran with **Node 24.22.1** against isolated instances of the application's real API, Temporal server, worker and HTTP ERP. CRM and inventory data were the repository's original synthetic fixtures. No Salesforce or MuleSoft provider was involved.

The [original runtime report](../../docs/evidence/n8n-qualification.json) and [service logs](../../docs/evidence/n8n-qualification.log) record:

| Check | Observed result |
| --- | --- |
| Import the unchanged versioned export | Exactly one inactive workflow imported |
| Missing inbound credential | HTTP 403; no business case created |
| Incorrect inbound credential | HTTP 403; no business case created |
| Authenticated n8n trigger | HTTP 202 with the application's durable receipt |
| Repeat the same source message | Same case ID; one case in storage |
| Requester attempts approval | HTTP 403 |
| Distinct approver submits the bound plan hash | Accepted; case reaches `COMPLETED` |
| CRM and ERP effects | One `APPLIED` effect per system; one attempt each |
| Fresh remote readback | Matches the expected state |
| Temporal result and history | Matching completed workflow; 41 history events |
| Cleanup | All fixture services stopped; source export unchanged |

The observed case and correlation ID is `96833239-6820-4458-ad82-d3b95d98769e`. Its Temporal workflow is `case-96833239-6820-4458-ad82-d3b95d98769e`. The measured trigger-to-completion time was approximately **1.18 seconds** for this single local case. Approval was submitted automatically through the distinct approver identity, so this measures no human waiting time and is not a throughput or production latency claim.

The local imported copy received two generated credential bindings and a loopback API URL, then was published using the supported n8n CLI. The versioned export remains inactive, with no credentials. Generated tokens, encrypted n8n state and fixture databases were confined to a temporary local directory and removed after shutdown. No external account or licence activation was requested.

## Reproduce the isolated qualification

The 2.47.5 package declares **Node >=24.0.0**; use its version-specific requirement rather than assuming that older Node versions mentioned in generic installation documentation apply. Install through npm, using an ignored local prefix:

```bash
npm install --prefix .local/n8n-runtime --save-exact --no-audit --no-fund n8n@2.47.5
uv run --locked python integrations/n8n/qualify_local.py \
  --output evidence-local/n8n-qualification.json
```

`qualify_local.py` supervises all listeners and its HTTP client in one process environment, using separate ephemeral databases, principals and random loopback ports. It caps n8n concurrency at one and business activity concurrency at two, sets Node memory limits and bounds total execution to 420 seconds. It never reuses the main local demonstration identities. Existing proxy settings remain in place for external destinations; explicit loopback exceptions prevent the local fixture traffic from using them.

The script uses the normal n8n import and publish commands. It does not alter n8n's implementation, write activation records directly, disable authentication or accept licence terms. The npm installation is not part of the production Python dependency set. [Installation evidence](../../docs/evidence/n8n-qualification.install.json) records the distribution integrity and the installation-specific dependency lock hash; the npm dependency graph has not received a separate security audit in this qualification.

## Preserved failures and harness correction

The first npm installation was terminated by SIGKILL after 165 seconds; the cause was not established. A coordinated attempt was interrupted while other qualification processes were running. The final normal npm install completed successfully with a 768 MiB Node heap cap and one native build job. The three logs and outcomes are linked from the installation report.

The [first runtime attempt](../../docs/evidence/n8n-qualification.initial.json) saw an unregistered webhook return 404 immediately after HTTP readiness. The harness now probes registration separately, with a bounded wait, before requiring an authentication refusal. n8n 2.47.5 applies publication through its publication service; HTTP readiness alone is insufficient evidence that a particular webhook is ready.

The [second runtime attempt](../../docs/evidence/n8n-qualification.proxy-failure.json) correctly refused unauthenticated requests but returned 500 for the authenticated trigger. Its log reports a non-JSON HTTP response. The harness had preserved npm proxy variables while removing the loopback exception. The [selector probe](../../docs/evidence/n8n-qualification.proxy.json) confirms that the installed `proxy-from-env` selected a proxy for loopback before the correction and selected none afterward. The successful run changed only the harness environment; the workflow export was unchanged.

After the successful run, independent review identified a CLI cleanup gap during global cancellation. The harness now terminates that process group and propagates cancellation. A dedicated regression using a sleeping CLI and a real child process verifies both processes exit; it is separate from n8n business-runtime qualification:

```bash
uv run --locked pytest -q integrations/n8n/test_qualify_local.py
```

The [harness review record](../../docs/evidence/n8n-qualification.harness-review.json) contains the SHA-256 captured from the executed harness before that patch, the final harness digest, and the passing cancellation check. The n8n business scenario was not rerun after this cancellation-only correction.

## Limits and official references

This qualifies the three-node HTTP intake path on the local npm runtime. The startup log reports an unavailable Python task runner; the workflow has no Python or Code node. Docker-image operation, external task runners, hosted n8n, provider credentials, Salesforce/MuleSoft behavior and production capacity are outside this result. See [vendor installation and qualification](../../docs/vendor-integration.md) for those boundaries.

- [Official n8n 2.47.5 release](https://github.com/n8n-io/n8n/releases/tag/n8n%402.47.5)
- [Official npm distribution metadata](https://registry.npmjs.org/n8n/2.47.5)
- [npm installation](https://docs.n8n.io/hosting/installation/npm/)
- [Supported import, export and publish CLI commands](https://docs.n8n.io/hosting/cli-commands/)
- [Versioned workflow publication implementation](https://github.com/n8n-io/n8n/blob/n8n%402.47.5/packages/cli/src/workflows/publication/workflow-publication-outbox-consumer.ts)
