# Public source publication

## Intended outcome and observed state

The maintainer authorized a public source repository on **14 November 2026** and will perform operations that require the GitHub interface. Public visibility is an authorized action, not an outstanding permission request. Account sign-in through an automated browser is not part of this publication workflow.

The most recent repository read still reported `private: true`. The implementation and its original evidence are in [PR #2](https://github.com/mehdisafer/crm-order-workflow-agent/pull/2). The default branch, `main`, now presents the project, an original operator screenshot, observed results and direct links to the runnable candidate and its evidence. This README-only change was reviewed and merged through [PR #3](https://github.com/mehdisafer/crm-order-workflow-agent/pull/3), at commit [`53314f0`](https://github.com/mehdisafer/crm-order-workflow-agent/commit/53314f0fc1160992c04aba4f4be98c825ba976ef). It changed no application code or workflow. Making the repository public exposes this useful overview and the candidate branch; it does not merge PR #2.

The source is suitable for review as an explicitly qualified local candidate: real Temporal recovery tests, actual Firefox/n8n exercises, a successful Mule package build and retained failure evidence. Actual Salesforce/MuleSoft acceptance and the reference container remain open. Those limits stay visible when the source becomes public; publication does not turn them into passed validations.

## Interface operations

The connected repository tools can update code, issues and pull requests and perform a merge. They do not expose an administration mutation for visibility, About metadata or branch protection. The following settings are prepared for the maintainer.

### 1. Make the exact repository public

In **mehdisafer/crm-order-workflow-agent**, open **Settings → General → Danger Zone → Change repository visibility**, select **Public**, review the displayed effects and complete GitHub's confirmation. The official [visibility procedure](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility) identifies the controls and consequences. Git history and Actions history/logs are part of the public exposure, so they were included in the review scope.

No source-history deletion, account upgrade, billing change or paid service is part of this action. The recorded source/history scan found no secrets, and the additional publication review identified original synthetic fixtures and PNG captures, with no vendor runtime/archive binaries committed. Temporary loopback addresses, tool versions and scratch paths remain in original evidence.

### 2. Inspect the CI startup annotations

Open the latest **CI** run for PR #2 and inspect its annotations. The last recorded delivery run is [43595327515](https://github.com/mehdisafer/crm-order-workflow-agent/actions/runs/43595327515): all three jobs failed before runner allocation, with no executed steps. The reason has not been established. This is not evidence that the tests themselves failed, and no billing or policy change should be inferred from the empty jobs.

The useful diagnostic is the non-secret annotation text and the run URL. Once the cause is known and the authorized runner path is available, execute the existing CI. The required jobs are **Core contracts and security**, **Temporal recovery** and **Reference container build**. The container job must actually build and run the PostgreSQL/HTTP ERP stack and its Chromium checks. Do not count a skipped or never-started job as success.

### 3. Apply About metadata

Suggested description:

> Auditable order-exception workflows with Temporal, scoped approvals, Salesforce/MuleSoft integration source and recovery evidence.

Suggested topics:

`python`, `data-engineering`, `temporal`, `salesforce`, `mulesoft`, `workflow`, `data-integration`, `saga`, `idempotency`, `fastapi`, `n8n`, `portfolio`

Leave the website field empty until an actual authorized deployment exists. The local operator screenshots are evidence of the local profile, not a hosted production application.

### 4. Deliver the implementation to the default branch

After the CI gate is satisfied, merge PR #2 at its reviewed head. The source and evidence are already committed, so this does not require rebuilding the project from another directory. Verify the resulting `main` README, source, guides and screenshot links. Preserve issue #1 for the remaining actual-provider and operational acceptance work.

Apply the available branch protections after checking their exact settings: require the PR path and the three named checks, prevent force pushes/deletion and preserve review conversations. Do not invent an independent human approval or purchase a plan to satisfy a proposed setting.

## Licence and release identity

No licence has been selected for this repository. Public visibility and an open-source licence are separate matters in GitHub's [licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository). An actual licence grant requires the maintainer's choice; neither a licence used by another project nor dependency metadata determines it here.

When selected, add the exact standard licence text and align the README, package metadata and licence checks. Until then, describe the project as public source, with its licence undecided. Third-party licences and vendor/runtime terms remain applicable.

The prepared `0.1.0-rc.1` notes describe a local candidate. No public release or tag has been issued. Any eventual release must state its actual source commit and retain the open provider qualification rather than imply a completed production deployment.

## Observable source-publication checks

- GitHub reports public visibility for this exact repository.
- Anonymous readers can open the default-branch overview and its direct links to the candidate source, evidence and actual screenshots.
- The overview states where the runnable candidate lives and identifies the application PR's actual status.
- The selected licence is consistent across files, or its undecided status remains explicit.
- The source/evidence identities and open provider acceptance issue remain accessible.

Delivery of the application to `main` is a subsequent, separately observable milestone: the required CI jobs execute successfully, PR #2 is merged at its reviewed head, and source/guide/screenshot links work from the resulting default branch. Actual-provider acceptance remains open until its own scenarios run. Neither milestone is implied by the visibility setting or the README-only merge.

The [settings proposal](../.github/repository-settings.json) is a declarative handoff, not an executed GitHub configuration. Historical evidence files retain the repository state observed at their capture time.
