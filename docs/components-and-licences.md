# Component inventory and licence status

The repository's own licence is intentionally undecided. The maintainer must select it explicitly before public distribution. Package metadata does not grant a licence to this project's source.

`uv.lock` pins the Python dependency graph and distribution hashes. [components.json](evidence/components.json) records the observed installed development environment, including test/audit tooling, package versions, authors, URLs and declared licences. [dependency-audit.json](evidence/dependency-audit.json) separately audits the locked runtime subset. An inventory or a clean current advisory lookup is not a certification and does not cover deployed Salesforce/MuleSoft permissions.

| Direct component | Declared licence in inspected package metadata |
| --- | --- |
| FastAPI, Pydantic, SQLAlchemy, Temporal Python SDK, PyYAML | MIT |
| HTTPX, Starlette, Uvicorn | BSD family; retain each package's actual notice |
| prometheus-client | Apache-2.0 AND BSD-2-Clause |
| Psycopg and psycopg-binary | LGPL-3.0-only; keep distribution notices and assess redistribution requirements for the chosen release |

The container installs dependencies with their package metadata and licence files; this repository does not relicense them. Actual compliance for a distributed image must account for its final binary contents and intended distribution. No claim of legal certification is made.

Salesforce and MuleSoft are provider/runtime products with their own terms. This repository includes original integration source and references, not a vendor runtime, licence key or entitlement. n8n has its own source-available/commercial terms, documented in [vendor-sources.md](vendor-sources.md); the workflow export does not change those terms. Docker images likewise retain their component licences.

The optional PostgreSQL qualification helper is outside the runtime dependency graph. Its version and embedded PostgreSQL version are recorded with the exercise. It is used only for a disposable loopback test and is not the reference deployment image.

Before a dependency update or public binary release, rerun the locked audit, regenerate the inventory, investigate newly unknown/changed licences and retain the relevant upstream notices. Do not silently change the repository licence to make an inventory check pass.
