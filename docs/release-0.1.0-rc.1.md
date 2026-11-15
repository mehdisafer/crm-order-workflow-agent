# Release candidate 0.1.0-rc.1 — local workflow V1

This prerelease packages the public **local, synthetic** order-exception workflow, including the runnable operator desk and durability/recovery evidence. The Python package version is `0.1.0rc1` (PEP 440); the Git tag is `v0.1.0-rc.1`. It is **not** a Salesforce/MuleSoft production deployment or full P06 provider acceptance.

## Delivered business capability

A fictional industrial service operator submits a delivery-date exception; the application resolves customer/order, checks synthetic inventory, builds a typed plan, obtains approval from a separate identity and executes a Temporal-coordinated CRM update plus stock reservation. It rereads the observed states and shows approvals, effects, compensation decisions, conflicts and escalation in the operator view.

## What was exercised

- The earlier isolated Python qualification passed **91 tests**, with real Temporal history replay, killed-worker recovery and persistent-server restart. See [historical evidence](evidence/README.md) and its exact source identities.
- The [GitHub Actions PR run 43767041683, attempt 2](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43767041683/attempts/2) completed all three jobs successfully: core security/contracts, real Temporal recovery and reference Docker/HTTP/PostgreSQL plus Chrome browser checks. These results apply to its reviewed candidate/merge ref, not automatically to later commits.
- The [first post-merge main run 43768042601](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43768042601) passed Core and Temporal, but its Chromium launcher failed before page creation. The release-candidate CI patch uses the system Chrome executable. A subsequent browser run exposed a fixture collision: the HTTP smoke and browser requested the same future date, which the business rule correctly rejected as `NO_CHANGE_NEEDED`. The browser now chooses a distinct future date from observed case state. A later real run completed the entire browser workflow but exposed a 526px mobile document overflow against the 390px viewport, traced to an off-screen hidden table span. The release candidate positions the scrollable table as a clipping context without dropping accessibility text. Both corrections require their own new CI result. [Detailed observations](evidence/ci-main-20261115.md).
- Firefox desktop/narrow-viewport, n8n 2.47.5 authenticated trigger, a bounded 24-case/two-worker local load and PostgreSQL logical backup/restore have separate original evidence in the same index.
- MuleSoft's application **package** built against its declared 4.9.24 target. Actual running Mule and Salesforce identities, permissions, OAuth limits and remote effect reconciliation have **not** been qualified.

## Open acceptance and constraints

Actual Salesforce/MuleSoft operation, an appropriately invalidated approval, real provider-side permission refusal, lost-response recovery without duplicated provider writes, vendor OAuth/429/timeouts and combined operational-platform recovery remain open in [issue #1](https://github.com/mehdisafer/crm-order-workflow-agent/issues/1). No commercial notifications or transactions are sent; all bundled fixtures are synthetic. Public distribution does not imply vendor certification.

The local workflow is a **release candidate**, not a production-ready system. It is automatically tagged and published only after a successful CI run on the current `main` commit; the release body links the exact successful run. A missing CI result cannot be replaced by a previous PASS.

## License and reproducibility

Original application code, documentation and fixtures are licensed under [Apache-2.0](../LICENSE). Third-party libraries, the n8n runtime and Salesforce/MuleSoft products retain their applicable licences and terms.

From the tagged source (or its exact commit), run:

```bash
uv sync --locked
uv run --locked python -m crm_workflow.cli smoke
```

The first run may download the official Temporal test-server binary. The [operator guide](operator-guide.md), [operations and recovery guide](operations.md), [architecture](architecture.md) and [provider installation guide](vendor-integration.md) retain the reproducible commands and limitations. Stop/rollback does not delete remote effects or assume transactional reversibility.
