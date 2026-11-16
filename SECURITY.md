# Security policy

## Scope and supported release

This public repository is a **portfolio demonstration using synthetic data**. The maintained line is `main`; the only issued tag is the pre-release [`v0.1.0-rc.1`](https://github.com/mehdisafer/crm-order-workflow-agent/releases/tag/v0.1.0-rc.1), which is not a production-support or vendor-certified release. Security fixes and triage are best effort; no response or patch SLA is offered. Historical tags and prior commits should not be treated as ongoing supported production versions.

Known *unverified integration gates* are tracked openly in [issue #1](https://github.com/mehdisafer/crm-order-workflow-agent/issues/1): real Salesforce/MuleSoft permissions, token lifecycle, remote deduplication and coordinated operational recovery have not been accepted. Do not interpret local simulator tests as verification of those vendor behaviors.

## Report a vulnerability privately

For a vulnerability affecting this repository's code, **do not include exploit steps, secrets, account details, customer data or access tokens in public GitHub issues, PRs or Discussions**.

1. Open the repository's [Security advisories](https://github.com/mehdisafer/crm-order-workflow-agent/security/advisories).
2. If **Report a vulnerability** is available, submit the details through GitHub private vulnerability reporting. Include affected revision, impact, reproduction using **synthetic** fixtures, and proposed mitigation when possible.
3. If the private-reporting option is absent, file only a **non-sensitive request to establish a private reporting channel**, without exploit details or secrets. The maintainer must enable a confidential channel before any sensitive report can be shared.

GitHub's private vulnerability reporting **availability has not been verified** for this repository. The owner should enable it under **Settings → Security and quality → Advanced Security → Private vulnerability reporting** when that control is available. This policy file alone does not enable private reporting.

## Review boundaries

Security-relevant changes must preserve tenant isolation, least privilege, separate approval, bounded retries, conditional compensation, immutable effect identity, redacted logs and synthetic-only fixtures. Verify actual remote permissions on an expressly authorized provider environment; local permission denials are not vendor security evidence.

Do not submit vulnerabilities found on third-party Salesforce, MuleSoft or n8n runtimes as if this repository owns them. Follow each provider's own disclosure process. The [operational guide](docs/operations.md) covers credential handling and recovery limitations; source policy is not a promise of deployed infrastructure protection.
