# Contributing

This is a publicly licensed, **synthetic** industrial order-exception demonstration. Contributions should improve a reproducible user-visible or engineering outcome without claiming Salesforce/MuleSoft deployment or provider rights that were not observed.

## Start from a reviewed checkout

Use Python 3.12 and [uv](https://docs.astral.sh/uv/). The initial Temporal profile may download its test-server binary. Run from the repository root:

```bash
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -m "not temporal and not vendor and not load"
RUN_TEMPORAL_TESTS=1 uv run --locked pytest -m temporal
```

On PowerShell, set `$env:RUN_TEMPORAL_TESTS = '1'` before the final command. Real Temporal integration tests are not substitutes for an authorized provider sandbox. Optional bounded smoke and Docker/reference commands are in the [README](README.md) and [operations guide](docs/operations.md). Do not run load tests against external providers without a separately approved scope.

## Propose focused changes

1. Review the current [acceptance matrix](docs/acceptance.md), especially the **open** Salesforce/MuleSoft acceptance gate. For a large change, describe the business problem in an issue before implementation. Do not attach secrets or live customer records.
2. Create a focused feature branch and PR against `main`. State what was requested, implemented, executed and **actually verified**, with the exact commit and reproduction steps. Follow the [PR template](.github/pull_request_template.md).
3. Add business-policy regression tests whenever changing approvals, identity/tenant boundaries, retries, idempotence, effect reconciliation, rollback or operator state. Preserve stable case/effect identities and the intent of a distinct approver.
4. Keep contracts and mappings versioned. A new operation or adapter requires reviewed authorization and readback semantics; a test mock does not establish Salesforce access control, Mule retry behavior or remote write idempotence.
5. Run the checks relevant to the change. Do not call a skipped test, unassigned runner or historical CI green a new PASS. Explicitly link failure reports and unresolved gates.

Generated credentials and local databases must stay in ignored `.local/`; local test outputs belong in ignored `evidence-local/`. Avoid printing full environment configuration, bearer tokens, provider payloads, private keys or sensitive exception messages in issues, commits and CI logs. Original evidence under `docs/evidence/` is immutable historical observation; create a separate dated record for genuinely new tests rather than overwriting it.

## Maintainer review and releases

The maintained source is `main`. The versioned [`v0.1.0-rc.1` pre-release](https://github.com/mehdisafer/crm-order-workflow-agent/releases/tag/v0.1.0-rc.1) remains pinned to its qualified commit; later merges do not silently move its tag. A green CI check covers only its exact ref and configured scope. External-provider validation requires a separately authorized nonproduction environment.

The original project source is [Apache-2.0](LICENSE). Contributors must ensure they can submit their changes under this project's license and retain third-party notices and rights. Vendor runtimes, client code and nonredistributable assets must never be copied into this repository. See the [component license inventory](docs/components-and-licences.md) and [security policy](SECURITY.md) before posting reports.
