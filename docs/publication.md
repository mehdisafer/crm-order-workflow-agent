# Public source publication and local V1

## Observed release boundary

The repository [mehdisafer/crm-order-workflow-agent](https://github.com/mehdisafer/crm-order-workflow-agent) was switched to **Public** on 15 November 2026. GitHub recognizes the [Apache-2.0 licence](../LICENSE), and the About description and eleven technology topics are configured. [PR #2](https://github.com/mehdisafer/crm-order-workflow-agent/pull/2) delivered the application to `main` at commit [`e37e007`](https://github.com/mehdisafer/crm-order-workflow-agent/commit/e37e00763254c2287117148e7050f27f6fc1c2c5). The default branch contains the source and original synthetic evidence; the earlier README-only PR #3 and licence PR #4 remain preserved in history.

This is the **local V1 release candidate**, not complete P06 provider acceptance. Actual Salesforce/MuleSoft scenarios remain open in [issue #1](https://github.com/mehdisafer/crm-order-workflow-agent/issues/1). No vendor runtime, tenant data or commercial communication is publicly deployed.

## CI and qualification

- [PR run 43767041683, attempt 2](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43767041683/attempts/2): all three GitHub Actions jobs succeeded on actual allocated runners. The reference job executed the containerized PostgreSQL/HTTP ERP stack and a Chrome desktop/mobile request/approval/readback journey.
- [First main run 43768042601](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43768042601): core and Temporal succeeded; the browser step failed at Chromium launch. The release-candidate CI update uses system Chrome and `--exercise true`, matching the known successful PR profile. This fix must itself pass CI before release.
- GitHub's status API also reported success for `ci/circleci: build-and-test` on the original implementation PR head. It covers the configured Python core suite only; it does not replace Temporal or Docker/browser checks.
- [Evidence index](evidence/README.md) distinguishes historical local executions, current CI results and still-unverified provider/operational claims.

Do not describe a build as accepted merely because its workflow is configured, an older commit passed or a runner started. The release workflow verifies that the exact *current `main` SHA* successfully completed the full CI workflow before creating the immutable `v0.1.0-rc.1` tag/prerelease.

## Release mechanism

The checked-in `.github/workflows/release-rc.yml` listens for successful `CI` `push` workflows on `main`. Before publishing it verifies the current branch SHA, `pyproject.toml` version `0.1.0rc1`, matching root lockfile identity, Apache-2.0 metadata and the absence of a conflicting pre-existing tag/release. It publishes a **GitHub prerelease** under `v0.1.0-rc.1`, with [release notes](release-0.1.0-rc.1.md) and the qualifying run link. It neither publishes to PyPI nor creates a cloud service or vendor deployment. Any release failure remains visible in its own Actions job and must not be described as successful.

No release tag or GitHub release is asserted until their existence is confirmed through GitHub.

## Owner interface handoff

The [main branch](https://github.com/mehdisafer/crm-order-workflow-agent/tree/main) remains **unprotected** at the last observed settings read. Via the repository **Settings → Rules → Rulesets** or branch protection interface, apply supported controls without a plan upgrade: require pull requests, prevent force pushes and deletion, and require `Core contracts and security`, `Temporal recovery` and `Reference container build` after they are observed on `main`. Preserve automated review evidence without pretending it is independent human approval.

No Chrome/Tinyfish account sign-in, personal workstation connector, billing change or client access is needed. Public anonymous access to the README, source and original screenshot should be verified separately after the default-branch and release changes.

## Provider/operational work that is not closed

Real provider acceptance requires an authorized Salesforce environment and Mule runtime, dedicated Reader/Executor identities, successful Apex tests, permitted HTTPS/OAuth configuration, actual rights denial, stale-approval refusal, idempotent lost-response recovery, quota/429 behavior and joint platform recovery. These remain in [acceptance.md](acceptance.md) and [issue #1](https://github.com/mehdisafer/crm-order-workflow-agent/issues/1). Publication of local V1 does not silently reduce the original P06 scope.
