# Public source publication and local V1

## Observed release boundary

The repository [mehdisafer/crm-order-workflow-agent](https://github.com/mehdisafer/crm-order-workflow-agent) was switched to **Public** on 15 November 2026. GitHub recognizes the [Apache-2.0 licence](../LICENSE), and the About description and eleven technology topics are configured. [PR #2](https://github.com/mehdisafer/crm-order-workflow-agent/pull/2) delivered the application to `main` at commit [`e37e007`](https://github.com/mehdisafer/crm-order-workflow-agent/commit/e37e00763254c2287117148e7050f27f6fc1c2c5). The default branch contains the source and original synthetic evidence; the earlier README-only PR #3 and licence PR #4 remain preserved in history.

This is the **local V1 release candidate**, not complete P06 provider acceptance. Actual Salesforce/MuleSoft scenarios remain open in [issue #1](https://github.com/mehdisafer/crm-order-workflow-agent/issues/1). No vendor runtime, tenant data or commercial communication is publicly deployed.

## CI and qualification

- [PR run 43767041683, attempt 2](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43767041683/attempts/2): all three GitHub Actions jobs succeeded on actual allocated runners. The reference job executed the containerized PostgreSQL/HTTP ERP stack and a Chrome desktop/mobile request/approval/readback journey.
- [First main run 43768042601](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43768042601) preserved the Chromium launch failure; later date-fixture and mobile-overflow failures were also retained. [Qualified release-source main CI 43770254516](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43770254516) passed all three jobs after those corrections. [Post-release main CI 43772725456](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43772725456) also passed after test-only PR #9.
- GitHub's status API also reported success for `ci/circleci: build-and-test` on the original implementation PR head. It covers the configured Python core suite only; it does not replace Temporal or Docker/browser checks.
- [Evidence index](evidence/README.md) distinguishes historical local executions, current CI results and still-unverified provider/operational claims.

Do not describe a build as accepted merely because its workflow is configured, an older commit passed or a runner started. The release workflow verifies that the exact *current `main` SHA* successfully completed the full CI workflow before creating the immutable `v0.1.0-rc.1` tag/prerelease.

## Release mechanism

The checked-in `.github/workflows/release-rc.yml` responds only to successful CI push workflows on current `main`, checks the immutable source SHA, package/lock version `0.1.0rc1` and Apache-2.0, then creates the single GitHub prerelease. This actually occurred. On later successful CI it performs no mutation if the release already exists, rather than moving its original tag. No PyPI, vendor system or public business API was deployed.

The [GitHub prerelease `v0.1.0-rc.1`](https://github.com/mehdisafer/crm-order-workflow-agent/releases/tag/v0.1.0-rc.1) exists, confirmed on original source SHA `cdf3c0e` with [release workflow 43770391572](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43770391572) successful. After test-only changes, `main` advanced to `4dc6e2a`; [publisher run 43772866253](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43772866253) completed without altering the prior tag. Main and release SHAs now intentionally differ.

## Owner interface handoff

**Main protection observed 16 November 2026.** The [default branch](https://github.com/mehdisafer/crm-order-workflow-agent/tree/main) now reports `protected: true`. GitHub's [active repository ruleset `main-protection-v1`](https://github.com/mehdisafer/crm-order-workflow-agent/rules/27410179), targeting `~DEFAULT_BRANCH`, prohibits deletion and non-fast-forward changes, requires a pull request and resolved review threads, and strictly requires four existing CI contexts: `Core contracts and security`, `Temporal recovery`, `Reference container build` and `ci/circleci: build-and-test`. The ruleset has zero bypass actors and currently requires **zero approving reviews**; therefore it enforces a PR path but does not establish independent human approval. The classic branch-protection details endpoint remains inaccessible to this integration; this ruleset readback is the concrete observed enforcement. GitHub Actions has an unfiltered `pull_request` trigger and CircleCI defines its ordinary branch workflow. Recheck the exact emitted check names after future workflow changes; do not mandate a job that cannot run on the relevant PRs.

No Chrome/Tinyfish account sign-in, personal workstation connector, billing change or client access is needed. Public anonymous access to the README, source and original screenshot should be verified separately after the default-branch and release changes.

## Provider/operational work that is not closed

Real provider acceptance requires an authorized Salesforce environment and Mule runtime, dedicated Reader/Executor identities, successful Apex tests, permitted HTTPS/OAuth configuration, actual rights denial, stale-approval refusal, idempotent lost-response recovery, quota/429 behavior and joint platform recovery. These remain in [acceptance.md](acceptance.md) and [issue #1](https://github.com/mehdisafer/crm-order-workflow-agent/issues/1). Publication of local V1 does not silently reduce the original P06 scope.
