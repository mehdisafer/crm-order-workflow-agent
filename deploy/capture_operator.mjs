// Development-only UI verification. Playwright is deliberately not a production dependency.
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { createHash, randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";

const options = {};
for (let i = 2; i < process.argv.length; i += 2) options[process.argv[i]] = process.argv[i + 1];
const target = new URL(options["--url"] || "http://127.0.0.1:8000");
if (!['127.0.0.1', 'localhost', '[::1]'].includes(target.hostname)
    || !["http:", "https:"].includes(target.protocol) || target.username || target.password) {
  throw new Error("UI capture only permits an explicitly local demo endpoint");
}
const require = createRequire(import.meta.url);
const moduleRoot = options["--modules"] || process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES;
const playwrightPath = moduleRoot ? require.resolve("playwright", { paths: [moduleRoot] }) : require.resolve("playwright");
const playwright = require(playwrightPath);
const engine = options["--engine"] || "chromium";
if (!["chromium", "firefox", "webkit"].includes(engine)) throw new Error("Unknown browser engine");
const exercise = options["--exercise"] === "true";
const tokens = JSON.parse(await fs.readFile(options["--tokens"] || ".local/tokens.json", "utf8"));
for (const role of exercise ? ["requester", "approver", "operator"] : ["operator"]) {
  if (typeof tokens[role] !== "string" || tokens[role].length < 24) throw new Error(`Missing local ${role} credential`);
}
const output = options["--output"] || (engine === "chromium" ? "evidence-local/browser" : `evidence-local/${engine}-ui`);
await fs.mkdir(output, { recursive: true });
const redact = (value) => Object.values(tokens).reduce((text, secret) => text.replaceAll(secret, "[REDACTED]"), String(value));
const report = {
  captured_at: new Date().toISOString(),
  status: "running",
  browser_engine: engine,
  browser_version: null,
  node_version: process.version,
  playwright_version: require(path.join(path.dirname(playwrightPath), "package.json")).version,
  profile: "observed-local-operator-ui",
  provider_validation: false,
  exercise_requested: exercise,
  source_files_sha256: {},
  page_errors: [],
  console_errors: [],
  http_errors: [],
  failed_requests: [],
  external_requests_blocked: [],
  screenshots: [],
};
for (const file of ["deploy/capture_operator.mjs", "deploy/qualify_operator.py", "src/crm_workflow/static/index.html", "src/crm_workflow/static/styles.css", "src/crm_workflow/static/app.js"]) {
  const contents = await fs.readFile(new URL(`../${file}`, import.meta.url));
  report.source_files_sha256[file] = createHash("sha256").update(contents).digest("hex");
}
try {
  report.base_source_commit = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
} catch { report.base_source_commit = null; }

const assert = (condition, message) => { if (!condition) throw new Error(message); };
const responseFor = (page, method, pathname) => page.waitForResponse((response) =>
  response.request().method() === method && new URL(response.url()).pathname === pathname);

async function connect(page, role) {
  await page.locator("#access-token").fill(tokens[role]);
  const [response, queue] = await Promise.all([
    responseFor(page, "GET", "/api/v1/session"),
    responseFor(page, "GET", "/api/v1/cases"),
    page.locator("#connect-button").click(),
  ]);
  assert(response.status() === 200 && queue.status() === 200, "Identity or case list was refused");
  const session = await response.json();
  assert(session.profile === "demo", "Browser qualification refuses a non-demo profile");
  await page.waitForFunction(() => document.querySelector("#access-token").value === "");
  assert(await page.locator("#case-detail").isHidden(), "Switching identity did not clear the case view");
  const caseQueue = await queue.json();
  assert(Array.isArray(caseQueue.items), "The authenticated case list is malformed");
  return { ...session, cases: caseQueue.items };
}

async function openCase(page, caseId) {
  if (caseId) await page.locator("#search").fill(caseId);
  const button = page.locator("#case-rows button").first();
  await button.waitFor({ state: "visible", timeout: 15000 });
  const [response] = await Promise.all([
    page.waitForResponse((response) => response.request().method() === "GET"
      && /^\/api\/v1\/cases\/[^/]+$/.test(new URL(response.url()).pathname)),
    button.click(),
  ]);
  assert(response.status() === 200, "Case view request failed");
  const item = await response.json();
  if (caseId) assert(item.id === caseId, "The selected case differs from the exercised case");
  await page.locator("#case-detail").waitFor({ state: "visible" });
  return item.id;
}

async function exerciseWorkflow(page) {
  const started = Date.now();
  const requester = await connect(page, "requester");
  const previousDates = requester.cases
    .map((item) => item.reconciliation?.crm_order)
    .filter((order) => order?.reference === "ORD-1001")
    .map((order) => order.requested_date)
    .filter((value) => typeof value === "string");
  // The HTTP reference smoke changes ORD-1001 first. A duplicate target is a valid
  // NO_CHANGE_NEEDED decision, not a workflow eligible for an approval.
  let requestedDate = options["--requested-date"];
  if (!requestedDate) {
    for (let days = 10; days <= 75; days += 1) {
      const candidate = new Date(Date.now() + days * 86400000).toISOString().slice(0, 10);
      if (!previousDates.includes(candidate)) {
        requestedDate = candidate;
        break;
      }
    }
  }
  assert(requestedDate, "No distinct future date was available for the synthetic browser case");
  const messageId = `browser-${randomUUID()}`;
  await page.locator("#new-top").click();
  await page.locator("#customer-reference").fill("invalid reference with spaces");
  assert(await page.locator("#customer-reference").evaluate((input) => input.validity.patternMismatch),
    "The browser did not enforce the identifier pattern");
  await page.locator("#customer-reference").fill("CUST-001");
  await page.locator("#order-reference").fill("ORD-1001");
  await page.locator("#requested-date").fill(requestedDate);
  await page.locator("#message-id").fill(messageId);
  await page.locator("#request-note").fill("Synthetic browser qualification: delivery date requested through the operator form.");
  const [submitted] = await Promise.all([
    responseFor(page, "POST", "/api/v1/cases"),
    page.locator("#submit-request").click(),
  ]);
  assert(submitted.status() === 202, "Form submission was not accepted");
  const created = await submitted.json();
  assert(created.request.message_id === messageId && created.requester_id === requester.actor.actor_id,
    "The accepted case does not match the requester form");
  await page.locator("#case-state").filter({ hasText: /^Awaiting approval$/ }).waitFor({ state: "visible", timeout: 90000 });
  const plan = JSON.parse(await page.locator("#plan-json").textContent());
  assert(plan.requested_date === requestedDate, "The displayed plan does not match the requested date");
  assert(await page.locator("#approve").isDisabled(), "The requester was offered self-approval");
  const approver = await connect(page, "approver");
  assert(approver.actor.actor_id !== requester.actor.actor_id, "Approval needs a different actual principal");
  await openCase(page, created.id);
  assert(JSON.parse(await page.locator("#plan-json").textContent()).hash === plan.hash,
    "The displayed approval scope changed during identity switching");
  assert(await page.locator("#approve").isEnabled(), "The separate approver cannot act on the pending plan");
  const [approved] = await Promise.all([
    responseFor(page, "POST", `/api/v1/cases/${created.id}/approval`),
    page.locator("#approve").click(),
  ]);
  assert(approved.status() === 202, "The browser approval was not accepted");
  assert(approved.request().postDataJSON().plan_hash === plan.hash, "The browser approved a different plan hash");
  await page.locator("#case-state").filter({ hasText: /^Completed$/ }).waitFor({ state: "visible", timeout: 90000 });
  const operator = await connect(page, "operator");
  await openCase(page, created.id);
  const [readback] = await Promise.all([
    responseFor(page, "POST", `/api/v1/cases/${created.id}/reconcile`),
    page.locator("#reconcile").click(),
  ]);
  assert(readback.status() === 200, "The browser reconciliation request failed");
  const final = await readback.json();
  assert(final.state === "COMPLETED" && final.reconciliation?.matches === true, "Current readback does not match completion");
  assert(final.effects.length === 2 && final.effects.every((effect) => effect.status === "APPLIED"),
    "Expected one observed CRM effect and one observed inventory effect");
  assert(final.approval.actor_id === approver.actor.actor_id, "Recorded approval does not match the browser approver");
  await page.locator("#readback-result h4").filter({ hasText: "Observed state matches" }).waitFor({ state: "visible" });
  assert(await page.locator(".change-card").getByText("Delivery at proposal", { exact: true }).isVisible(),
    "The proposal date is not identified as a historical snapshot");
  const crmLabels = await page.locator("#effects-list .effect").filter({ hasText: "CRM ·" }).locator("dt").allTextContents();
  assert(crmLabels.includes("Order quantity") && !crmLabels.includes("Reserved quantity"),
    "The CRM order quantity is presented as an inventory reservation");
  assert(await page.locator("#effects-list .effect").filter({ hasText: "Inventory ·" }).getByText("Reserved quantity", { exact: true }).isVisible(),
    "The observed inventory reservation quantity is missing");
  report.exercise = {
    performed: true,
    case_id: created.id,
    message_id: messageId,
    requester_id: requester.actor.actor_id,
    approver_id: approver.actor.actor_id,
    operator_id: operator.actor.actor_id,
    form_submission_http_status: submitted.status(),
    invalid_reference_rejected_by_browser: true,
    requester_approval_button_disabled: true,
    separate_approver: true,
    browser_approval_http_status: approved.status(),
    browser_reconciliation_http_status: readback.status(),
    approved_plan_hash: plan.hash,
    before_date: plan.order.requested_date,
    requested_date: requestedDate,
    previously_observed_order_dates: previousDates,
    default_date_avoids_existing_remote_state: !previousDates.includes(requestedDate),
    state: final.state,
    effects: final.effects.map(({ system, status, attempts }) => ({ system, status, attempts })),
    remote_readback_matches: final.reconciliation.matches,
    proposal_snapshot_label_verified: true,
    crm_and_reserved_quantities_distinguished: true,
    event_types: final.events.map(({ event_type }) => event_type),
    duration_seconds: (Date.now() - started) / 1000,
    human_wait_note: "Requester and approver interactions were automated through the actual UI; no real human waiting time was measured.",
  };
  return created.id;
}

async function observe(page, context) {
  const result = await page.evaluate((secrets) => {
    const visibleAndInputText = document.body.textContent + [...document.querySelectorAll("input, textarea")].map((node) => node.value).join("\n");
    return {
      horizontal_overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      document_width: document.documentElement.scrollWidth,
      viewport_width: document.documentElement.clientWidth,
      password_input_empty: document.querySelector("#access-token").value === "",
      token_present_in_dom: secrets.some((secret) => visibleAndInputText.includes(secret)),
      local_storage_keys: Object.keys(localStorage).length,
      session_storage_keys: Object.keys(sessionStorage).length,
      case_state: document.querySelector("#case-state").textContent.trim(),
      environment_label: document.querySelector("#environment").textContent.trim(),
      overflow_elements: [...document.querySelectorAll("body *")]
        .filter((element) => {
          const rect = element.getBoundingClientRect();
          return rect.width > 0 && rect.right > document.documentElement.clientWidth + 1;
        }).slice(0, 12).map((element) => ({ tag: element.tagName, id: element.id, width: element.getBoundingClientRect().width })),
    };
  }, Object.values(tokens));
  result.cookies = (await context.cookies()).length;
  assert(result.password_input_empty && !result.token_present_in_dom, "A credential remains in the rendered page or input");
  assert(result.local_storage_keys === 0 && result.session_storage_keys === 0 && result.cookies === 0,
    "The browser retained storage or cookies during the token-memory check");
  return result;
}

let browser;
try {
  browser = await playwright[engine].launch({
    headless: true,
    ...(engine === "chromium" ? { chromiumSandbox: true } : {}),
    ...(engine === "chromium" && process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}),
  });
  report.browser_version = browser.version();
  let caseId = options["--case-id"];
  for (const [name, viewport] of [["desktop", { width: 1440, height: 1100 }], ["mobile", { width: 390, height: 844 }]]) {
    const context = await browser.newContext({ viewport, deviceScaleFactor: 1, colorScheme: "light", locale: "en-GB", timezoneId: "UTC" });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    let recording = true;
    page.on("pageerror", (error) => report.page_errors.push(redact(error.message)));
    page.on("console", (message) => {
      if (message.type() === "error") report.console_errors.push(redact(message.text()));
    });
    page.on("response", (response) => {
      if (recording && response.status() >= 400) report.http_errors.push({ view: name, path: new URL(response.url()).pathname, status: response.status() });
    });
    page.on("requestfailed", (request) => {
      if (recording) report.failed_requests.push({ view: name, path: new URL(request.url()).pathname, error: redact(request.failure()?.errorText) });
    });
    await page.route("**/*", (route) => {
      const url = new URL(route.request().url());
      if (url.origin === target.origin) return route.continue();
      report.external_requests_blocked.push({ view: name, origin: url.origin });
      return route.abort();
    });
    await page.goto(target.href, { waitUntil: "networkidle" });
    if (name === "desktop" && exercise) caseId = await exerciseWorkflow(page);
    else {
      await connect(page, "operator");
      caseId = await openCase(page, caseId);
    }
    for (const [section, selector] of [["overview", "body"], ["detail", "#case-detail"], ["readback", "#readback-heading"]]) {
      await page.locator(selector).evaluate((element) => element.scrollIntoView({ block: "start" }));
      const observation = await observe(page, context);
      const file = path.join(output, `operator-${name}-${section}.png`);
      await page.screenshot({ path: file, fullPage: false });
      const digest = createHash("sha256").update(await fs.readFile(file)).digest("hex");
      report.screenshots.push({ name, section, viewport, file: path.relative(process.cwd(), file), sha256: digest, case_id: caseId, ...observation });
    }
    await page.locator("#disconnect-button").click();
    assert(await page.locator("#case-detail").isHidden() && await page.locator("#case-identifiers").textContent() === "",
      "Disconnecting did not clear the case view");
    await observe(page, context);
    recording = false;
    await context.close();
  }
  report.disconnect_clears_case_view = true;
  report.status = report.page_errors.length || report.console_errors.length || report.http_errors.length
    || report.failed_requests.length || report.external_requests_blocked.length
    || report.screenshots.some((item) => item.horizontal_overflow) ? "failed" : "passed";
} catch (error) {
  const message = redact(error.message);
  report.status = message.includes("browserType.launch") ? "blocked" : "failed";
  report.failure_code = message.includes("Operation not permitted") ? `${engine.toUpperCase()}_OS_PERMISSION_DENIED` : "BROWSER_EXECUTION_FAILED";
  report.failure_summary = message.includes("Operation not permitted")
    ? `${engine} launch was denied by the operating system before page creation.`
    : message.split("\n")[0];
} finally {
  if (browser) await browser.close();
  await fs.writeFile(path.join(output, "operator-browser.json"), JSON.stringify(report, null, 2) + "\n");
}
console.log(JSON.stringify({ status: report.status, browser_engine: engine, case_id: report.exercise?.case_id, screenshots: report.screenshots.map(({ file }) => file), page_errors: report.page_errors.length, console_errors: report.console_errors.length, http_errors: report.http_errors.length }));
if (report.status !== "passed") {
  process.exitCode = 1;
}
