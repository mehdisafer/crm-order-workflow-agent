// Development-only UI verification. Playwright is deliberately not a production dependency.
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

const options = {};
for (let i = 2; i < process.argv.length; i += 2) options[process.argv[i]] = process.argv[i + 1];
const target = new URL(options["--url"] || "http://127.0.0.1:8000");
if (!['127.0.0.1', 'localhost', '[::1]'].includes(target.hostname)) {
  throw new Error("UI capture only permits an explicitly local demo endpoint");
}
const require = createRequire(import.meta.url);
const moduleRoot = options["--modules"] || process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES;
const playwrightPath = moduleRoot ? require.resolve("playwright", { paths: [moduleRoot] }) : require.resolve("playwright");
const { chromium } = require(playwrightPath);
const tokens = JSON.parse(await fs.readFile(options["--tokens"] || ".local/tokens.json", "utf8"));
const output = options["--output"] || "docs/evidence";
await fs.mkdir(output, { recursive: true });
const redact = (value) => Object.values(tokens).reduce((text, secret) => text.replaceAll(secret, "[REDACTED]"), String(value));
const report = {
  captured_at: new Date().toISOString(),
  status: "running",
  browser_version: null,
  node_version: process.version,
  playwright_version: require(path.join(path.dirname(playwrightPath), "package.json")).version,
  profile: "observed-local-operator-ui",
  provider_validation: false,
  page_errors: [],
  console_errors: [],
  screenshots: [],
};
let browser;
try {
  browser = await chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}),
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  report.browser_version = browser.version();
  for (const [name, viewport] of [["desktop", { width: 1440, height: 1100 }], ["mobile", { width: 390, height: 844 }]]) {
    const context = await browser.newContext({ viewport, deviceScaleFactor: 1, colorScheme: "light" });
    const page = await context.newPage();
    page.on("pageerror", (error) => report.page_errors.push(redact(error.message)));
    page.on("console", (message) => {
      if (message.type() === "error") report.console_errors.push(redact(message.text()));
    });
    await page.route("**/*", (route) => {
      const url = new URL(route.request().url());
      return url.origin === target.origin ? route.continue() : route.abort();
    });
    await page.goto(target.href, { waitUntil: "networkidle" });
    await page.locator("#access-token").fill(tokens.operator);
    await page.locator("#connect-button").click();
    await page.locator("#case-rows button").first().waitFor({ state: "visible", timeout: 15000 });
    await page.locator("#case-rows button").first().click();
    await page.locator("#case-detail").waitFor({ state: "visible" });
    await page.locator("#case-detail").evaluate((element) => element.scrollIntoView({ block: "start" }));
    await page.waitForTimeout(150);
    const observation = await page.evaluate(() => ({
      horizontal_overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      document_width: document.documentElement.scrollWidth,
      viewport_width: document.documentElement.clientWidth,
      password_input_empty: document.querySelector("#access-token").value === "",
      case_state: document.querySelector("#case-state").textContent.trim(),
      environment_label: document.querySelector("#environment").textContent.trim(),
      overflow_elements: [...document.querySelectorAll("body *")]
        .filter((element) => {
          const rect = element.getBoundingClientRect();
          return rect.width > 0 && rect.right > document.documentElement.clientWidth + 1;
        })
        .slice(0, 12)
        .map((element) => ({ tag: element.tagName, id: element.id, width: element.getBoundingClientRect().width })),
    }));
    if (!observation.password_input_empty) throw new Error("Credential input was not cleared after login");
    const file = path.join(output, `operator-${name}.png`);
    await page.screenshot({ path: file, fullPage: false });
    report.screenshots.push({ name, viewport, file, ...observation });
    await context.close();
  }
  report.status = report.page_errors.length || report.console_errors.length || report.screenshots.some((item) => item.horizontal_overflow) ? "failed" : "passed";
} catch (error) {
  const message = redact(error.message);
  report.status = message.includes("browserType.launch") ? "blocked" : "failed";
  report.failure_code = message.includes("Operation not permitted") ? "CHROMIUM_OS_PERMISSION_DENIED" : "BROWSER_EXECUTION_FAILED";
  report.failure_summary = message.includes("Operation not permitted")
    ? "Chromium aborted before page creation: process_singleton_posix.cc socket() failed: Operation not permitted (1)."
    : message.split("\n")[0];
} finally {
  if (browser) await browser.close();
  await fs.writeFile(path.join(output, "operator-browser.json"), JSON.stringify(report, null, 2) + "\n");
}
console.log(JSON.stringify({ status: report.status, screenshots: report.screenshots.map(({ file }) => file), page_errors: report.page_errors.length, console_errors: report.console_errors.length }));
if (report.status !== "passed") {
  process.exitCode = 1;
}
