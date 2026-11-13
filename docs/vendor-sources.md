# Vendor implementation sources

Checked on **13 November 2026**. These official sources informed implementation choices, not an executed compatibility certification. No vendor account or commercial entitlement was inferred from the existence of documentation.

| Source | Decision supported |
| --- | --- |
| [Salesforce REST API authorization](https://developer.salesforce.com/docs/platform/api-rest/guide/intro-oauth-and-connected-apps.html) | OAuth with External Client Apps; new Connected App creation is restricted from Spring 2026. |
| [Salesforce database access mode](https://developer.salesforce.com/docs/platform/apex-dev/references/apex-dev/apex-classes-enforce-usermode.html) | Explicit `WITH USER_MODE`, `AccessLevel.USER_MODE` and user-mode DML at pinned API 65.0; avoid depending on newer default behavior. |
| [Salesforce Apex CRUD/FLS enforcement](https://developer.salesforce.com/docs/platform/apex-dev/references/apex-dev/apex-classes-perms-enforcing.html) | Sharing and object/field permissions are separate controls. |
| [Salesforce row locking](https://developer.salesforce.com/docs/platform/apex-dev/references/apex-dev/langcon-apex-locking-statements.html) | `FOR UPDATE` protects the conditional read/write interval; lock contention and stale callers still require explicit handling. |
| [Salesforce custom exceptions](https://developer.salesforce.com/docs/platform/apex-dev/references/apex-dev/apex-exception-custom.html) | Typed errors retain a safe status/code without exposing raw CRM exceptions. |
| [Salesforce test runAs](https://developer.salesforce.com/docs/platform/apex-dev/references/apex-dev/apex-testing-tools-runas.html) | Tests execute with distinct scoped identities; actual tenant permission proof still requires execution. |
| [Salesforce mixed DML in tests](https://developer.salesforce.com/docs/platform/apex-dev/references/apex-dev/apex-dml-non-mix-sobjects-test-methods.html) | User/permission fixture setup is isolated from synthetic business records using `System.runAs`. |
| [Mule runtime 4.9 release notes](https://docs.mulesoft.com/release-notes/mule-runtime/mule-4.9.0-release-notes) | The observed November patch is 4.9.24; it is the source configuration target. |
| [Mule Java support](https://docs.mulesoft.com/general/java-support) | Runtime and connector Java compatibility must be verified together; this deployment targets Java 17. |
| [Mule Maven plugin 4.10.4](https://docs.mulesoft.com/release-notes/mule-maven-plugin/mule-maven-plugin-4.10.4-release-notes) | Version released 4 November 2026; documented Maven 3.9–3.10 and runtime compatibility. |
| [Mule HTTP connector release notes](https://docs.mulesoft.com/release-notes/connector/connector-http) | Pin 1.12.2, released 8 October 2026; verify transitive resolution during packaging. |
| [Mule OAuth module release notes](https://docs.mulesoft.com/release-notes/connector/oauth-module-release-notes) | Pin 1.1.30, released 19 October 2026; token requests have a documented sixty-second bound. |
| [Mule HTTP built-in retry configuration](https://docs.mulesoft.com/http-connector/latest/http-request-ref) | Disable the default remotely-closed retry mechanism with JVM `maxRetries=0`; keep `retryOnAllMethods=false`. |
| [Mule 4.9 system properties](https://docs.mulesoft.com/mule-runtime/4.9/mule-app-properties-system) | Standalone startup uses `-M-D` arguments. Observe the selected running JVM; YAML properties alone do not establish JVM values. |
| [Mule HTTP authentication](https://docs.mulesoft.com/http-connector/1.10/http-authentication) | Configure client credentials in the request connection; deployment can require an initial token exchange. |
| [Mule OAuth module reference](https://docs.mulesoft.com/oauth-module/latest/oauth-module-reference) | Refresh can retry the API callback. Override the default condition to refresh on 401 only, preserving 403 denial semantics. |
| [Mule enterprise license installation](https://docs.mulesoft.com/mule-runtime/4.9/installing-an-enterprise-license) | Evaluation and production rights differ; do not redistribute a runtime or assume a production license. |
| [n8n 2.47.5 release](https://github.com/n8n-io/n8n/releases/tag/n8n%402.47.5) | Target the observed 12 November 2026 release; container retrieval/import is a separate check. |
| [n8n Webhook node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook) | Native header authentication and response-node workflow. |
| [n8n HTTP Request node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest) | Bind credentials outside the workflow export and forward the intake body to the application. |
| [n8n license](https://github.com/n8n-io/n8n/blob/master/LICENSE.md) | Sustainable Use and Enterprise terms are distinct from this project's license; no generic open-source or SaaS redistribution claim. |

## Evidence limits

Source XML/JSON/Python syntax checks were run. They cannot compile Apex, resolve a Mule dependency graph, test provider permissions, or establish exactly-once remote effects. A first provider run must retain the real org/runtime versions, allowed synthetic scope, deployment/test outputs, request IDs and recorded readbacks. Record missing prerequisites as `BLOCKED` or `NOT_EXECUTED`, not as a skipped test counted as passing.
