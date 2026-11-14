# Mule packaging evidence — 14 November 2026

## Observed result

The Mule application was packaged successfully with **Mule Maven plugin 4.10.4**, **Apache Maven 3.10.0** and **Amazon Corretto 17.0.21**. The POM explicitly selects runtime target **4.9.24**. Maven reported `BUILD SUCCESS` after **3 minutes 24 seconds**; the bounded process wrapper recorded 205.797 seconds including command startup.

The generated `p06-crm-system-api-0.1.0-mule-application.jar` is 3,456,304 bytes with SHA-256 `b637c34e288209b0f18454c07069b8257a18d3e7d3a24dc858eba66847341b91`. Inspection observed its generated Mule AST, the `crm-system-api.xml` configuration, a descriptor requiring Mule 4.9.24 and Java 17, and 12 bundled JARs. Both exact connector artifacts are included: HTTP 1.12.2 and OAuth 1.1.30. The external example configuration is not bundled. Binaries, Maven caches and machine-specific proxy settings are kept outside this repository.

**This is packaging evidence. Provider acceptance remains OPEN.** No Mule server or Salesforce org was started, deployed to or used for a business request. No Apex tests, MUnit scenarios, OAuth token exchange, remote permission test, retry-behavior test or provider recovery scenario ran.

## Warnings retained

The successful build reported these unresolved checks:

- `${P06_RUNTIME_CONFIG}` was reported as an invalid configuration for the `file` parameter during package analysis.
- `${gateway.tlsKeyStore}` was reported as an invalid configuration for the TLS `path` parameter during package analysis.
- Unconsumed-stream validation was skipped with `cfgProvider=false` and `expressionLanguageMetadataService=false`.

The full output also retains duplicate-module warnings, repository cache warnings and a 401 response for automatically discovered private-repository metadata. The build completed using publicly resolvable artifacts without vendor credentials. Those warnings were not suppressed, and no artificial configuration or secrets were bundled to make runtime validation appear successful. The selected server must still verify external configuration, TLS, OAuth, actual connector behavior and permissions.

## Dependency inventory and original failure

The first `dependency:tree` command failed because its temporary Maven settings referenced the executor proxy from an earlier completed tool execution. The recorded errors are connection refusals followed by plugin-prefix resolution failure. The second command regenerated its isolated settings from the current executor-provided proxy and forced a new resolution attempt. It succeeded and produced `mule-dependency-tree.txt`. The original failure is retained alongside that result.

| Evidence | Meaning |
| --- | --- |
| `maven-package-attempt-1.log` and `.json` | Original complete package output, command, return code and bounded duration |
| `maven-version.txt` | Actual Maven and Java versions used |
| `maven-acquisition.json`, `jdk17-acquisition.json` | Official distribution URLs, resolved JDK version and verified checksums |
| `build-inputs.json` | SHA-256 identity of package inputs, including the modified POM, compared with the final checkout |
| `attempt-1-source-manifest.json` | Complete source-copy manifest captured before the build; documentation subsequently evolved |
| `package-inspection.json`, `archive-inventory.json`, `classloader-model.json` | Actual descriptor, generated AST size, resolved classloader model and bundled-JAR hashes |
| `maven-dependency-tree.log` and `.json` | Original failed inventory command |
| `maven-dependency-tree-attempt-2.log` and `.json` | Successful inventory command after refreshing the ordinary executor proxy |
| `mule-dependency-tree.txt` | Actual resolved application dependency tree |
| `original-output-digests.json` | SHA-256 digests of the unchanged copied original outputs |

The source baseline was PR #2 head `06ace725336bfd62e38bfb8cbb8f4a173c7652e0`. The POM used for this build includes the subsequent explicit runtime selection and public-repository corrections. `build-inputs.json` binds the evidence to those exact inputs; it does not claim the unchanged baseline already contained those fixes.

The archive inventory is not a comprehensive SBOM, vulnerability audit or assessment of runtime licensing rights. A runtime qualification must record the installed server version, entitlement, effective properties, authorized synthetic scope and observed provider effects separately.

## Exact server access check — 14 November 2026

An official anonymously obtainable **Mule 4.9.24 standalone server** was not established by this bounded check. The [Mule 4.9 on-premises installation procedure](https://docs.mulesoft.com/on-premises/4.9/runtime-installation-task) directs Enterprise standalone acquisition to the MuleSoft Support portal or an account representative. The [standalone patching guide](https://docs.mulesoft.com/release-notes/mule-runtime/patching-mule-versions) identifies the customer portal as the source of full distributions containing current patches. The [Enterprise licensing guide](https://docs.mulesoft.com/mule-runtime/4.9/installing-an-enterprise-license) distinguishes evaluation from production rights; the existence of a trial is not evidence that this session holds those rights.

An anonymous GET of the [public Kernel distribution catalog](https://repository.mulesoft.org/releases/org/mule/distributions/mule-standalone/maven-metadata.xml) returned HTTP 200. Its listed versions included `4.9.0`, `4.10.0`, `4.11.0` and `4.12.0`, but not `4.9.24`. An anonymous HEAD of `https://repository.mulesoft.org/releases/org/mule/distributions/mule-standalone/4.9.24/mule-standalone-4.9.24.zip` returned HTTP 404. This establishes the result for that published catalog and exact artifact path; it does not prove that no other authorized distribution channel exists.

The remaining runtime gate is an authorized exact standalone distribution together with its applicable evaluation or Enterprise usage rights. No alternate Mule version, trial registration, account creation, terms acceptance or server startup was used. The public Maven tooling and application dependencies used for packaging do not satisfy this server-access gate, and no local Salesforce stub was used as provider validation.
