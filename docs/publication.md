# Public source publication

## Intended outcome and observed state

The maintainer authorized a public source repository on **14 November 2026** and will perform operations that require the GitHub interface. Public visibility is an authorized action, not an outstanding permission request. Account sign-in through an automated browser is not part of this publication workflow.

The most recent repository read still reported `private: true`. The implementation and its original evidence are in [PR #2](https://github.com/mehdisafer/crm-order-workflow-agent/pull/2). The default branch, `main`, now presents the project, an original operator screenshot, observed results and direct links to the runnable candidate and its evidence. This README-only change was reviewed and merged through [PR #3](https://github.com/mehdisafer/crm-order-workflow-agent/pull/3), at commit [`53314f0`](https://github.com/mehdisafer/crm-order-workflow-agent/commit/53314f0fc1160992c04aba4f4be98c825ba976ef). It changed no application code or workflow. Making the repository public exposes this useful overview and the candidate branch; it does not merge PR #2.

The source is suitable for review as an explicitly qualified local candidate: real Temporal recovery tests, actual Firefox/n8n exercises, a successful Mule package build and retained failure evidence. Actual Salesforce/MuleSoft acceptance and the reference container remain open. Those limits stay visible when the source becomes public; publication does not turn them into passed validations.

## Interface operations

The available GitHub connector was inspected again on **15 November 2026**. The following boundary separates an unavailable administration operation from a source change that the connector can perform.

| Operation | Available route |
| --- | --- |
| Update source, documentation, branches, issues and PRs | GitHub connector |
| Select and commit the `Apache-2.0` licence to `main` | Completed in [PR #4](https://github.com/mehdisafer/crm-order-workflow-agent/pull/4); package metadata aligned on the application branch |
| Re-run failed Actions jobs | GitHub connector; an actual rerun was accepted on 15 November |
| Merge PR #2 after its execution gate is satisfied | GitHub connector; no browser sign-in is needed |
| Change visibility or branch protections | Maintainer's GitHub interface; no administration mutation is exposed by this connector (About metadata is already configured) |
| Read the startup failure annotation text | Maintainer's interface; the connector's allowed endpoints do not expose these check-run details |

The GitHub API now confirms that the description and eleven technology topics are present. The remaining visibility/protection operations below are prepared for the maintainer; these cannot be applied through this GitHub connector.

### 1. Make the exact repository public

In **mehdisafer/crm-order-workflow-agent**, open **Settings → General → Danger Zone → Change repository visibility**, select **Public**, review the displayed effects and complete GitHub's confirmation. The official [visibility procedure](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility) identifies the controls and consequences. Git history and Actions history/logs are part of the public exposure, so they were included in the review scope.

No source-history deletion, account upgrade, billing change or paid service is part of this action. The recorded source/history scan found no secrets, and the additional publication review identified original synthetic fixtures and PNG captures, with no vendor runtime/archive binaries committed. Temporary loopback addresses, tool versions and scratch paths remain in original evidence.

### 2. Inspect the CI startup annotations

Open the [Checks tab of PR #2](https://github.com/mehdisafer/crm-order-workflow-agent/pull/2/checks) to select the latest run and inspect its annotations. The recorded 15 November recheck is [run 43602410931, attempt 2](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43602410931/attempts/2), for source `0c5357eebb8275df20db64346e158de1a38ea132`. GitHub accepted the rerun, but all three jobs again failed with runner ID 0, an empty runner name and no executed steps. Retrieval of the core job log returned `404 BlobNotFound`. The earlier run `43595327515` remains historical evidence. The current application commit `3c9d4d9` has also produced [run 43764852235](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43764852235): three failed jobs, runner ID 0 and zero executed steps. This is the most recent attempt inspected while updating this guide, not a permanent claim about future runs.

The [separate recheck record](evidence/publication-recheck-20261115.json) retains these observations. The platform reason has not been established. This is not evidence that the tests themselves failed, and no billing or policy change should be inferred from the empty jobs.

The useful diagnostic is the non-secret annotation text and the run URL. Once the cause is known and the authorized runner path is available, execute the existing CI. The required jobs are **Core contracts and security**, **Temporal recovery** and **Reference container build**. The container job must actually build and run the PostgreSQL/HTTP ERP stack and its Chromium checks. Do not count a skipped or never-started job as success.

### 3. Verify About metadata (already configured)

The GitHub repository API confirms the following description:

> Auditable order-exception workflows with Temporal, scoped approvals, Salesforce/MuleSoft integration source and recovery evidence.

Observed topics (11):

`python`, `data-engineering`, `temporal`, `salesforce`, `mulesoft`, `workflow`, `data-integration`, `saga`, `idempotency`, `fastapi`, `n8n`

Leave the website field empty until an actual authorized deployment exists. The local operator screenshots are evidence of the local profile, not a hosted production application.

### 4. Deliver the implementation to the default branch

After the CI gate is satisfied, merge PR #2 at its reviewed head through the GitHub connector. The source and evidence are already committed, so this does not require rebuilding the project from another directory or signing in through a browser. Verify the resulting `main` README, source, guides and screenshot links. Preserve issue #1 for the remaining actual-provider and operational acceptance work.

Apply the available branch protections after checking their exact settings: require the PR path and the three named checks, prevent force pushes/deletion and preserve review conversations. The CI workflow now triggers for every pull request, including documentation-only changes, so these required checks are not omitted by a path filter. The push trigger retains its documentation filter. GitHub documents why [skipping a required workflow by path leaves its checks pending](https://github.com/github/docs/blob/main/data/reusables/actions/workflows/triggering-a-workflow-paths2.md). This configuration correction does not establish that a runner can start. Do not invent an independent human approval or purchase a plan to satisfy a proposed setting.

## Parallel CircleCI configuration

The [CircleCI PR #5](https://github.com/mehdisafer/crm-order-workflow-agent/pull/5) was merged into the application branch. It contributes two configuration files for Python 3.12, locked uv, Ruff and the core test suite. The 2026 CircleCI `testsuite doctor/run` syntax is documented by CircleCI. **No hosted CircleCI execution has been observed**; the repository still needs to be connected to a CircleCI project through its own interface. This core suite does not replace Temporal and container/Chromium acceptance.

## Licence and release identity

The maintainer selected **Apache-2.0** on 15 November 2026. The complete standard `LICENSE` was merged to `main` via [PR #4](https://github.com/mehdisafer/crm-order-workflow-agent/pull/4) at commit [`1892087`](https://github.com/mehdisafer/crm-order-workflow-agent/commit/18920871022446f6bf284e22d8b071c26c93572b). The application branch includes that licence and declares `license = "Apache-2.0"` with `license-files = ["LICENSE"]` in `pyproject.toml`, following [PEP 639](https://peps.python.org/pep-0639/). This is a grant for the original project source, not for vendor products.

The licence text is unchanged from the [SPDX Apache-2.0 reference](https://github.com/spdx/license-list-data/blob/main/text/Apache-2.0.txt). Both READMEs and the package metadata identify Apache-2.0. Third-party dependencies, n8n and Salesforce/MuleSoft distribution/runtime terms remain applicable; historical audit files that predate selection are preserved rather than rewritten.

The prepared `0.1.0-rc.1` notes describe a local candidate. No public release or tag has been issued. Any eventual release must state its actual source commit and retain the open provider qualification rather than imply a completed production deployment.

## Observable source-publication checks

- GitHub reports public visibility for this exact repository.
- Anonymous readers can open the default-branch overview and its direct links to the candidate source, evidence and actual screenshots.
- The overview states where the runnable candidate lives and identifies the application PR's actual status.
- GitHub detects `Apache-2.0` on `main`, and the candidate package metadata and documentation declare the same licence.
- The source/evidence identities and open provider acceptance issue remain accessible.

Delivery of the application to `main` is a subsequent, separately observable milestone: the required CI jobs execute successfully, PR #2 is merged at its reviewed head, and source/guide/screenshot links work from the resulting default branch. Actual-provider acceptance remains open until its own scenarios run. Neither milestone is implied by the visibility setting or the README-only merge.

The [settings proposal](../.github/repository-settings.json) is a declarative handoff, not an executed GitHub configuration. Historical evidence files retain the repository state observed at their capture time.
