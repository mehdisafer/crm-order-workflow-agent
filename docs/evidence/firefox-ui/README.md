# Original Firefox UI qualification

The final recorded run exercised the actual UI over HTTP with the real Temporal workflow and a separately persisted, authenticated HTTP ERP. All orders, customers, notes and principals were generated synthetic fixtures. No Salesforce, MuleSoft, external LLM, container or physical mobile-device result is implied.

## Final observed result

The [browser report](final-run/operator-browser.json) records Firefox **153.0** with the locked development-only Playwright **1.62.1** package. The browser was launched normally, without custom flags, custom preferences or changes to OS/network restrictions. The official Playwright installer downloaded Firefox through its own official mirror fallback after the first CDN returned an invalid archive. Chromium remained blocked by the executor's socket policy; [that earlier report](../operator-browser.json) is unchanged.

Case `fc20b632-8f66-4970-891d-b2e2fc291af9` was created by filling and submitting the requester form. The browser checked that an invalid reference was rejected by native input validation, then submitted the valid synthetic request (`202`). It observed the requester approval control disabled, switched to the distinct approver, approved the same displayed plan hash (`202`), waited for `COMPLETED`, switched to the operator, and clicked **Read current state** (`200`, `matches=true`). Both effects were `APPLIED`, each with one recorded write attempt. The interactions were automated; their 8.057-second duration is not a measurement of human approval time.

The [runtime report](final-run/runtime.json) independently queried Temporal **1.32.2** through SDK **1.36.0**. It observed a completed workflow, its actual activity/event history, the same completed API case and the ERP's HTTP `200` reservation receipt. API, ERP, worker, Temporal and Firefox ran under one orchestration command with loopback listeners. The helper stopped its child processes after collecting the result; API/ERP exit code `-15` records that deliberate SIGTERM cleanup.

All six captured views had zero page errors, console errors, failed HTTP responses or failed requests, and no horizontal page overflow. Credential inputs were empty, no known token remained in the DOM, browser storage/cookies were empty, and disconnect cleared the case view. Desktop interactions exercised the request and approval handlers; the narrow viewport checked the completed case's responsive rendering and read controls.

| View | Desktop, 1440×1100 | Narrow viewport, 390×844 |
| --- | --- | --- |
| Overview and explicit demo badge | [PNG](final-run/operator-desktop-overview.png) | [PNG](final-run/operator-mobile-overview.png) |
| Completed case, proposal and approval context | [PNG](final-run/operator-desktop-detail.png) | [PNG](final-run/operator-mobile-detail.png) |
| Reconciliation and observed history | [PNG](final-run/operator-desktop-readback.png) | [PNG](final-run/operator-mobile-readback.png) |

The six final PNGs were visually inspected. The overview identifies the synthetic profile, the completed state and plan dates remain legible, and the detail/readback views distinguish the proposal snapshot, CRM order quantity and inventory reservation. No credential was visible. The [credential scan](credential-scan.json) additionally checked all 18 retained PNGs with Tesseract OCR and all seven run JSON files for the known local credential values; it found none. OCR can misread characters, so this complements the DOM/storage checks and visual review rather than proving the absence of every possible secret. Images were captured directly by Playwright and have not been edited.

## Retained attempts and corrections

| Evidence | Observed outcome and resulting action |
| --- | --- |
| [Initial connection report](initial-connection-refusal/operator-browser.json) | Firefox launched, but a browser in a separate executor command could not reach the API's isolated loopback namespace. No page or screenshot was created. All services and the browser were then placed under one orchestration command; no binding or network policy was weakened. |
| [First same-command browser report](operator-browser.json) and [runtime report](runtime.json) | The real UI workflow completed and screenshots were produced, but 15 console errors exposed invalid HTML identifier patterns under the browser's RegExp `v` mode. A separate harness receipt check incorrectly assumed an `:erp` suffix; it was changed to consume the actual returned effect key. Both failures remain recorded. |
| [Corrected-pattern browser report](corrected-run/operator-browser.json) and [runtime report](corrected-run/runtime.json) | The repeated real scenario passed with zero browser errors and a confirmed ERP receipt. Visual review then found two misleading labels: a historical proposal date called current, and CRM order quantity called reserved. |
| [Final browser report](final-run/operator-browser.json) and [runtime report](final-run/runtime.json) | A fresh synthetic case repeated the complete UI path after both label corrections. Browser assertions verify **Delivery at proposal**, CRM **Order quantity** and inventory **Reserved quantity**. These are the final UI screenshots. |

## Source and reproduction boundary

Every browser report records its base source commit and SHA-256 values for the capture script and served UI files. The final capture script, HTML, CSS and application JavaScript still match the final report. The base commit `06ace725336bfd62e38bfb8cbb8f4a173c7652e0` identifies the restored starting point; the recorded file digests include the subsequent UI/capture corrections and must be considered alongside that base commit.

After the final capture, a one-line hardening change in `deploy/qualify_operator.py` removed inherited `P06_*` environment overrides before setting the explicit demo configuration. That helper change was checked with Ruff and its formatter; it was not represented as another complete browser execution. Its captured digest is retained unchanged in the report, and the helper's delivered digest therefore differs. The served UI and capture script were not changed after the final run.

From the repository root, install the locked Python and browser development dependencies, then run:

```bash
uv sync --locked
mkdir -p .local/browser-tools
cp deploy/browser/package.json deploy/browser/package-lock.json .local/browser-tools/
npm ci --prefix .local/browser-tools --ignore-scripts --no-audit --no-fund
.local/browser-tools/node_modules/.bin/playwright install firefox
uv run --locked python deploy/qualify_operator.py \
  --engine firefox --output evidence-local/browser-firefox
```

The [qualification helper](../../../deploy/qualify_operator.py) creates fresh private local credentials and separate application/ERP databases, runs the actual services, invokes the [browser script](../../../deploy/capture_operator.mjs), and observes Temporal and ERP independently afterward. It makes no mocked API responses or page fixtures. The original run artifacts here are preserved; reproduction writes to the separate ignored output path above.

Chromium CI, the reference container deployment and authorised Salesforce/MuleSoft acceptance remain separate open gates. This local Firefox evidence does not close them.
