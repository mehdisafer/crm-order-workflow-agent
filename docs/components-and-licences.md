# Component inventory and licence status

The repository's own licence is intentionally undecided and requires an explicit maintainer selection. Public source publication has been authorized; changing GitHub visibility does not itself select an open-source licence. Package metadata does not grant a licence to this project's source. The [publication record](publication.md) tracks the separate decisions and observed settings.

`uv.lock` pins the Python dependency graph and distribution hashes. [components.json](evidence/components.json) records the observed installed development environment, including test/audit tooling, package versions, authors, URLs and declared licences. [dependency-audit.json](evidence/dependency-audit.json) separately audits the locked runtime subset. An inventory or a clean current advisory lookup is not a certification and does not cover deployed Salesforce/MuleSoft permissions.

| Direct component | Declared licence in inspected package metadata |
| --- | --- |
| FastAPI, Pydantic, SQLAlchemy, Temporal Python SDK, PyYAML | MIT |
| HTTPX, Starlette, Uvicorn | BSD family; retain each package's actual notice |
| prometheus-client | Apache-2.0 AND BSD-2-Clause |
| Psycopg and psycopg-binary | LGPL-3.0-only; keep distribution notices and assess redistribution requirements for the chosen release |

The container installs dependencies with their package metadata and licence files; this repository does not relicense them. Actual compliance for a distributed image must account for its final binary contents and intended distribution. No claim of legal certification is made.

Salesforce and MuleSoft are provider/runtime products with their own terms. This repository includes original integration source and references, not a vendor runtime, licence key or entitlement. n8n has its own source-available/commercial terms, documented in [vendor-sources.md](vendor-sources.md); the workflow export does not change those terms. Docker images likewise retain their component licences.

The 14 November [Mule packaging record](evidence/mule-build-20261114/README.md) separately identifies Maven 3.10.0, Corretto 17.0.21, the resolved application dependency tree and the 12 JARs actually bundled by Maven. The [browser record](evidence/firefox-ui/README.md) identifies the locked development-only Playwright package and actual Firefox version. The [n8n installation record](evidence/n8n-qualification.install.json) identifies the exact official npm artifact, Node version and observed install attempts. These tools and vendor artifacts are not part of the Python advisory result; the n8n installation was not dependency-audited, and the package inventories are not complete licence compatibility or vulnerability assessments. No acquired JDK, Maven distribution, Mule application binary, browser binary or runtime installation is committed to this repository.

The optional PostgreSQL qualification helper is outside the runtime dependency graph. Its version and embedded PostgreSQL version are recorded with the exercise. It is used only for a disposable loopback test and is not the reference deployment image.

Before a dependency update or public binary release, rerun the locked audit, regenerate the inventory, investigate newly unknown/changed licences and retain the relevant upstream notices. Do not silently change the repository licence to make an inventory check pass.
