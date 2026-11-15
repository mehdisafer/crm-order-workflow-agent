"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const terminal = new Set([
    "COMPLETED", "COMPENSATED", "RECONCILIATION_REQUIRED", "NEEDS_CLARIFICATION",
    "ESCALATED", "APPROVAL_INVALIDATED", "FAILED", "EXPIRED", "REJECTED",
  ]);
  const attention = new Set([
    "NEEDS_CLARIFICATION", "ESCALATED", "APPROVAL_INVALIDATED", "RECONCILIATION_REQUIRED", "FAILED",
  ]);
  const stateLabels = {
    RECEIVED: "Queued", AWAITING_APPROVAL: "Awaiting approval", APPROVED: "Approved",
    CRM_APPLIED: "CRM change observed", STOCK_RESERVED: "Stock reserved", COMPLETED: "Completed",
    COMPENSATED: "Compensated", RECONCILIATION_REQUIRED: "Reconciliation required",
    NEEDS_CLARIFICATION: "Needs clarification", ESCALATED: "Escalated",
    APPROVAL_INVALIDATED: "Approval invalidated", FAILED: "Failed", EXPIRED: "Expired", REJECTED: "Rejected",
    PREPARED: "Prepared only", UNKNOWN: "Outcome uncertain", APPLIED: "Effect observed",
  };
  let token = "";
  let session = null;
  let cases = [];
  let selected = null;
  let filter = "all";
  let refreshRunning = false;
  let epoch = 0;
  let selectionEpoch = 0;
  let actionRunning = false;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function showNotice(message, kind = "info") {
    const notice = $("notice");
    notice.textContent = message;
    notice.className = `notice ${kind}`;
    notice.hidden = !message;
  }

  function readable(value) {
    return String(value || "").replaceAll(/[_.]/g, " ").toLowerCase()
      .replace(/(^|\s)\S/g, (letter) => letter.toUpperCase());
  }

  function dateOnly(value) {
    if (!value) return "Not provided";
    const date = new Date(`${String(value).slice(0, 10)}T12:00:00Z`);
    return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleDateString(undefined, {
      day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
    });
  }

  function dateTime(value) {
    if (!value) return "Not recorded";
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? "Unrecognised timestamp" : date.toLocaleString(undefined, {
      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  }

  function badge(state) {
    const good = new Set(["COMPLETED", "APPLIED", "STOCK_RESERVED"]);
    const bad = new Set(["FAILED", "APPROVAL_INVALIDATED", "RECONCILIATION_REQUIRED", "UNKNOWN"]);
    const warn = new Set(["AWAITING_APPROVAL", "NEEDS_CLARIFICATION", "ESCALATED", "COMPENSATED"]);
    const tone = good.has(state) ? "success" : bad.has(state) ? "danger" : warn.has(state) ? "warning" : "";
    return element("span", `state-badge ${tone}`, stateLabels[state] || readable(state));
  }

  function fact(container, name, value) {
    const row = element("div");
    row.append(element("dt", "", name), element("dd", "", value === null || value === undefined ? "—" : String(value)));
    container.append(row);
  }

  function jsonDetails(label, value) {
    const details = element("details");
    details.append(element("summary", "", label), element("pre", "", JSON.stringify(value, null, 2)));
    return details;
  }

  function hasRole(role) {
    return Boolean(session?.actor?.roles?.includes(role));
  }

  async function api(path, { method = "GET", data, credential = token } = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    const headers = { Accept: "application/json" };
    if (credential) headers.Authorization = `Bearer ${credential}`;
    if (data !== undefined) headers["Content-Type"] = "application/json";
    try {
      const response = await fetch(path, {
        method, headers, body: data === undefined ? undefined : JSON.stringify(data),
        credentials: "omit", cache: "no-store", redirect: "error", signal: controller.signal,
      });
      let payload;
      try { payload = await response.json(); } catch { payload = {}; }
      if (!response.ok) {
        const error = new Error(payload.error?.message || "The service could not complete the request.");
        error.status = response.status;
        error.code = payload.error?.code;
        error.requestId = payload.error?.request_id;
        throw error;
      }
      return payload;
    } catch (error) {
      if (error.name === "AbortError") {
        throw new Error("The service did not respond within 12 seconds.");
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  function errorMessage(error) {
    return `${error.message || "The service is unavailable."}${error.requestId ? ` Request ID: ${error.requestId}.` : ""}`;
  }

  function clearData() {
    cases = [];
    selected = null;
    selectionEpoch += 1;
    $("case-detail").hidden = true;
    $("new-request-panel").hidden = true;
    $("queue-nav").classList.add("active");
    $("new-nav").classList.remove("active");
    for (const id of ["message-id", "request-note", "requested-date", "customer-reference", "order-reference", "search"]) $(id).value = "";
    for (const id of ["plan-json", "plan-facts", "crm-link", "effects-list", "readback-result", "timeline", "approval-facts",
      "approval-help", "approval-status", "request-facts", "original-note", "case-identifiers", "case-reason", "case-heading",
      "case-state", "before-date", "after-date", "phase-track"]) $(id).replaceChildren();
    filter = "all";
    document.querySelectorAll("[data-filter]").forEach((item) => {
      item.classList.toggle("active", item.dataset.filter === "all");
      item.setAttribute("aria-pressed", String(item.dataset.filter === "all"));
    });
    for (const id of ["metric-active", "metric-approval", "metric-attention", "metric-complete"]) $(id).textContent = "—";
    renderQueue();
  }

  function disconnect(announce = true) {
    epoch += 1;
    token = "";
    session = null;
    $("access-token").value = "";
    $("connection-status").textContent = "Disconnected";
    $("connection-dot").classList.remove("connected");
    $("environment").textContent = "Profile not connected";
    $("environment").className = "environment-badge";
    $("identity-description").textContent = "Use a locally issued credential. Your token stays in this tab’s memory and is cleared on disconnect.";
    $("connection-heading").textContent = "Connect your operator identity";
    $("identity-tags").replaceChildren();
    $("identity-tags").hidden = true;
    $("disconnect-button").hidden = true;
    $("connect-button").textContent = "Connect";
    $("queue-description").textContent = "Connect to load cases for your tenant.";
    $("last-refreshed").textContent = "No observations yet";
    for (const id of ["new-nav", "new-top", "refresh", "search"]) $(id).disabled = true;
    clearData();
    showNotice("");
    if (announce) showNotice("Disconnected. The access token and case data were cleared from this view.");
  }

  function renderIdentity() {
    $("connection-heading").textContent = session.actor.actor_id;
    $("identity-description").textContent = `Tenant: ${session.actor.tenant_id}. Paste another credential to switch identity; permissions are checked by the server.`;
    $("connection-status").textContent = "Connected";
    $("connection-dot").classList.add("connected");
    const demo = session.profile === "demo";
    $("environment").textContent = demo ? "Synthetic reference · demo" : "Salesforce via MuleSoft · provider profile";
    $("environment").className = `environment-badge ${demo ? "demo" : "provider"}`;
    $("identity-tags").replaceChildren(...session.actor.roles.map((role) => element("span", "identity-tag", readable(role))));
    $("identity-tags").hidden = false;
    $("disconnect-button").hidden = false;
    $("connect-button").textContent = "Switch";
    $("new-nav").disabled = !hasRole("requester");
    $("new-top").disabled = !hasRole("requester");
    $("refresh").disabled = false;
    $("search").disabled = false;
    $("queue-description").textContent = "Cases visible to your authenticated tenant. Server observations determine progress.";
    if (demo) {
      $("customer-reference").value = "CUST-001";
      $("order-reference").value = "ORD-1001";
    } else {
      $("customer-reference").value = "";
      $("order-reference").value = "";
    }
  }

  function renderMetrics() {
    $("metric-active").textContent = String(cases.filter((item) => !terminal.has(item.state)).length);
    $("metric-approval").textContent = String(cases.filter((item) => item.state === "AWAITING_APPROVAL").length);
    $("metric-attention").textContent = String(cases.filter((item) => attention.has(item.state)).length);
    $("metric-complete").textContent = String(cases.filter((item) => item.state === "COMPLETED").length);
  }

  function renderQueue() {
    const term = $("search").value.toLowerCase();
    const visible = cases.filter((item) => {
      const request = item.request || {};
      const text = `${item.id} ${request.customer_reference || ""} ${request.order_reference || ""} ${item.plan?.customer?.name || ""}`;
      const category = filter === "all" || (filter === "approval" && item.state === "AWAITING_APPROVAL")
        || (filter === "attention" && attention.has(item.state)) || (filter === "complete" && item.state === "COMPLETED");
      return category && text.toLowerCase().includes(term);
    });
    $("case-count").textContent = String(cases.length);
    $("case-rows").replaceChildren();
    for (const item of visible) {
      const row = element("tr", selected?.id === item.id ? "selected" : "");
      const ref = element("td");
      ref.append(element("strong", "", item.plan?.customer?.name || item.request?.customer_reference || "Customer unresolved"));
      ref.append(element("small", "", item.request?.order_reference || "Order not provided"));
      const date = element("td", "", dateOnly(item.request?.requested_date || item.plan?.requested_date));
      const status = element("td");
      status.append(badge(item.state));
      if (item.reconciliation?.matches === false) status.append(element("small", "drift", "Remote differences observed"));
      const updated = element("td", "", dateTime(item.updated_at));
      const action = element("td");
      const button = element("button", "button quiet open-case", "View →");
      button.type = "button";
      button.setAttribute("aria-label", `View case for ${item.request?.order_reference || item.id}`);
      button.addEventListener("click", () => openCase(item.id, true));
      action.append(button);
      row.append(ref, date, status, updated, action);
      $("case-rows").append(row);
    }
    $("queue-empty").hidden = visible.length !== 0;
    const empty = $("queue-empty");
    empty.querySelector("h3").textContent = !session ? "No cases loaded" : cases.length ? "No matching cases" : "Your queue is empty";
    empty.querySelector("p").textContent = !session ? "Connect an identity to view its work queue."
      : cases.length ? "Try another filter or search term."
        : hasRole("requester") ? "Create a synthetic request to start the first workflow." : "Submitted requests will appear here for your tenant.";
  }

  async function refresh({ quiet = false } = {}) {
    if (!session || refreshRunning || actionRunning) return;
    const currentEpoch = epoch;
    refreshRunning = true;
    try {
      const result = await api("/api/v1/cases");
      if (currentEpoch !== epoch) return;
      cases = result.items || [];
      renderMetrics();
      renderQueue();
      $("last-refreshed").textContent = `Last observed ${dateTime(new Date().toISOString())} · ${cases.length} cases returned`;
      if (selected) {
        const latest = cases.find((item) => item.id === selected.id);
        if (latest) renderDetail(latest);
        else await openCase(selected.id, false);
      }
      if (!quiet) showNotice("The queue was refreshed from the service.", "info");
    } catch (error) {
      if (currentEpoch !== epoch) return;
      if (error.status === 401) disconnect(false);
      showNotice(errorMessage(error), "error");
    } finally {
      refreshRunning = false;
    }
  }

  async function openCase(id, scroll) {
    if (!session) return;
    const currentEpoch = epoch;
    const currentSelection = ++selectionEpoch;
    try {
      const item = await api(`/api/v1/cases/${encodeURIComponent(id)}`);
      if (currentEpoch !== epoch || currentSelection !== selectionEpoch) return;
      renderDetail(item);
      renderQueue();
      if (scroll) $("case-detail").scrollIntoView({ behavior: "auto", block: "start" });
    } catch (error) {
      if (currentEpoch === epoch) showNotice(errorMessage(error), "error");
    }
  }

  function renderPlan(item) {
    const plan = item.plan;
    $("plan-empty").hidden = Boolean(plan);
    $("plan-content").hidden = !plan;
    if (!plan) return;
    $("before-date").textContent = dateOnly(plan.order.requested_date);
    $("after-date").textContent = dateOnly(plan.requested_date);
    const facts = $("plan-facts");
    facts.replaceChildren();
    fact(facts, "Customer", `${plan.customer.name} · ${plan.customer.reference}`);
    fact(facts, "Order", plan.order.reference);
    fact(facts, "Product / quantity", `${plan.order.sku} · ${plan.order.quantity} units`);
    fact(facts, "Available at proposal", `${plan.availability.available} units`);
    fact(facts, "CRM revision", plan.order.revision);
    fact(facts, "Inventory revision", plan.availability.revision);
    fact(facts, "Approved field", (plan.fields || ["requested_date"]).join(", "));
    fact(facts, "Policy", `${plan.policy_version} · ${readable(plan.risk)}`);
    $("plan-json").textContent = JSON.stringify(plan, null, 2);
    const links = $("crm-link");
    links.replaceChildren();
    const crmUrl = plan.order.crm_url || "";
    let trustedLink = false;
    try {
      const parsed = new URL(crmUrl);
      trustedLink = parsed.protocol === "https:" && !parsed.username && !parsed.password
        && (parsed.hostname.endsWith(".salesforce.com") || parsed.hostname.endsWith(".force.com"));
    } catch { /* A non-navigable object reference remains text. */ }
    if (trustedLink) {
      const link = element("a", "", "Open the Salesforce object ↗");
      link.href = crmUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      links.append(link);
    } else {
      links.append(element("span", "subtle", crmUrl.startsWith("demo://")
        ? "Synthetic CRM object — no Salesforce record is implied."
        : `CRM object reference: ${plan.order.order_id}`));
    }
  }

  function renderApproval(item) {
    const approval = item.approval;
    const plan = item.plan;
    const facts = $("approval-facts");
    facts.replaceChildren();
    const expired = plan && new Date(plan.expires_at).valueOf() <= Date.now();
    const ownCase = session?.actor?.actor_id === item.requester_id;
    const eligible = Boolean(plan && item.state === "AWAITING_APPROVAL" && hasRole("approver") && !ownCase && !expired && !actionRunning);
    $("approve").disabled = !eligible;
    $("reject").disabled = !eligible;
    $("approval-status").replaceChildren(badge(approval?.decision === "approve" ? "APPROVED"
      : approval?.decision === "reject" ? "REJECTED" : item.state === "AWAITING_APPROVAL" ? "AWAITING_APPROVAL" : item.state));
    if (approval) {
      $("approval-help").textContent = approval.decision === "approve"
        ? "This decision covers the recorded plan only. The worker checks the plan and preconditions again before writing."
        : "The plan was rejected. No new write is authorised by this decision.";
      fact(facts, "Decision by", approval.actor_id || "Not recorded");
      fact(facts, "Decision time", dateTime(approval.approved_at));
    } else if (!plan) {
      $("approval-help").textContent = "There is no plan available for approval.";
    } else if (expired) {
      $("approval-help").textContent = "The approval window has elapsed. The server will refuse this plan even if a stale view still shows it as awaiting approval.";
    } else if (ownCase) {
      $("approval-help").textContent = "You requested this change. A different authorised identity must approve or reject the plan.";
    } else if (!hasRole("approver")) {
      $("approval-help").textContent = "Connect an approver identity to record a decision for this exact plan.";
    } else {
      $("approval-help").textContent = "Review the customer, order, dates and stock snapshot. The decision binds the displayed plan fingerprint.";
    }
    fact(facts, "Requester", item.requester_id);
    if (plan) {
      fact(facts, "Expires", dateTime(plan.expires_at));
      fact(facts, "Plan fingerprint", `${plan.hash.slice(0, 16)}…`);
      fact(facts, "Compensation", plan.compensation_allowed ? "Conditional restore allowed" : "No automatic restore");
    }
  }

  function renderEffects(item) {
    const target = $("effects-list");
    target.replaceChildren();
    const effects = item.effects || [];
    if (!effects.length) {
      target.append(element("p", "inline-empty", "No effect has been prepared or observed."));
      return;
    }
    for (const effect of effects) {
      const card = element("section", "effect");
      const heading = element("div", "effect-header");
      const system = effect.system === "crm" ? "CRM" : effect.system === "erp" ? "Inventory" : readable(effect.system);
      heading.append(element("strong", "", `${system} · ${readable(effect.operation)}`), badge(effect.status));
      card.append(heading, element("p", "effect-key mono", effect.effect_key));
      const facts = element("dl", "facts-grid");
      fact(facts, "Write attempts", effect.attempts ?? "Not recorded");
      fact(facts, "Remote evidence", effect.after ? "Observed snapshot recorded" : "No committed outcome observed");
      if (effect.before?.requested_date || effect.after?.requested_date) {
        fact(facts, "Before", dateOnly(effect.before?.requested_date));
        fact(facts, "After", dateOnly(effect.after?.requested_date));
        fact(facts, "Revision before", effect.before?.revision);
        fact(facts, "Revision after", effect.after?.revision);
      }
      if (effect.after?.quantity) {
        const quantityLabel = effect.system === "erp" ? "Reserved quantity"
          : effect.system === "crm" ? "Order quantity" : "Quantity";
        fact(facts, quantityLabel, effect.after.quantity);
      }
      card.append(facts, jsonDetails("Inspect effect intent and observed snapshots", effect));
      target.append(card);
    }
  }

  function renderReadback(item) {
    const observed = item.reconciliation;
    const target = $("readback-result");
    target.replaceChildren();
    $("reconcile").disabled = !hasRole("operator") || actionRunning;
    if (!observed) {
      target.className = "inline-empty";
      target.textContent = item.state === "COMPLETED"
        ? "The workflow completed after its execution readback. An operator can request a fresh observation to detect later changes."
        : "No independent reconciliation is recorded. An operator can read the current remote state without applying another change.";
      return;
    }
    target.className = `readback-result ${observed.matches === true ? "" : "warning"}`;
    target.append(element("h4", "", observed.matches === true ? "Observed state matches the recorded case"
      : observed.matches === false ? "Remote differences require attention" : "Readback recorded — inspect the evidence"));
    target.append(element("p", "", `Observed ${dateTime(observed.checked_at)}. Workflow state: ${stateLabels[item.state] || item.state}.`));
    target.append(jsonDetails("Inspect CRM and inventory observations", observed));
  }

  function renderTimeline(item) {
    const target = $("timeline");
    target.replaceChildren();
    for (const event of [...(item.events || [])].reverse()) {
      const row = element("li");
      const time = element("time", "", dateTime(event.created_at));
      if (event.created_at) time.dateTime = event.created_at;
      row.append(element("strong", "", readable(event.event_type)), time);
      if (event.payload && Object.keys(event.payload).length) row.append(jsonDetails("Recorded detail", event.payload));
      target.append(row);
    }
    if (!target.childNodes.length) target.append(element("li", "subtle", "No timeline events returned."));
  }

  function renderPhases(item) {
    const effects = item.effects || [];
    const applied = (system) => effects.some((effect) => effect.system === system && ["APPLIED", "COMPENSATED"].includes(effect.status));
    const phases = [
      ["Request accepted", Boolean(item.id)], ["Plan recorded", Boolean(item.plan)],
      ["Decision recorded", Boolean(item.approval)], ["CRM effect observed", applied("crm")],
      ["Stock effect observed", applied("erp")], ["Completion readback", item.state === "COMPLETED"],
    ];
    $("phase-track").replaceChildren(...phases.map(([label, observed]) => {
      const node = element("li", observed ? "observed" : "", label);
      node.setAttribute("aria-label", `${label}: ${observed ? "recorded" : "not recorded"}`);
      return node;
    }));
  }

  function renderDetail(item) {
    selected = item;
    $("case-detail").hidden = false;
    $("case-heading").textContent = item.request?.order_reference || "Order unresolved";
    $("case-identifiers").textContent = `Case ${item.id} · Correlation ${item.correlation_id}`;
    $("case-state").replaceChildren(badge(item.state));
    $("case-reason").textContent = item.reason || "";
    $("case-reason").hidden = !item.reason;
    renderPhases(item);
    renderPlan(item);
    renderApproval(item);
    renderEffects(item);
    renderReadback(item);
    renderTimeline(item);
    const facts = $("request-facts");
    facts.replaceChildren();
    fact(facts, "Message ID", item.request?.message_id);
    fact(facts, "Created", dateTime(item.created_at));
    fact(facts, "Customer ref.", item.request?.customer_reference);
    fact(facts, "Order ref.", item.request?.order_reference);
    $("original-note").textContent = item.request?.message || "No free-text note supplied.";
  }

  function showNewRequest() {
    if (!hasRole("requester")) return;
    if (!$("message-id").value) $("message-id").value = crypto.randomUUID();
    if (!$("requested-date").value) {
      const tomorrow = new Date();
      tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
      $("requested-date").value = tomorrow.toISOString().slice(0, 10);
    }
    $("new-request-panel").hidden = false;
    $("queue-nav").classList.remove("active");
    $("new-nav").classList.add("active");
    $("new-request-panel").scrollIntoView({ behavior: "auto", block: "start" });
    $("customer-reference").focus();
  }

  function closeNewRequest() {
    $("new-request-panel").hidden = true;
    $("queue-nav").classList.add("active");
    $("new-nav").classList.remove("active");
  }

  async function recordDecision(decision) {
    if (!selected?.plan || actionRunning) return;
    const currentEpoch = epoch;
    const caseId = selected.id;
    const planHash = selected.plan.hash;
    actionRunning = true;
    renderApproval(selected);
    try {
      const item = await api(`/api/v1/cases/${encodeURIComponent(caseId)}/approval`, {
        method: "POST", data: { plan_hash: planHash, decision },
      });
      if (currentEpoch !== epoch) return;
      renderDetail(item);
      showNotice(decision === "approve"
        ? "The approval was recorded. The worker will recheck its scope and the remote preconditions."
        : "The rejection was recorded.", "success");
    } catch (error) {
      if (currentEpoch === epoch) showNotice(`${errorMessage(error)}${!error.status ? " Refresh the case before attempting another decision." : ""}`, "error");
    } finally {
      actionRunning = false;
      if (currentEpoch === epoch && selected) {
        renderApproval(selected);
        await refresh({ quiet: true });
      }
    }
  }

  $("connect-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const candidate = $("access-token").value.trim();
    if (!candidate || actionRunning) return;
    disconnect(false);
    const currentEpoch = epoch;
    $("connect-button").disabled = true;
    try {
      const nextSession = await api("/api/v1/session", { credential: candidate });
      if (currentEpoch !== epoch) return;
      token = candidate;
      session = nextSession;
      renderIdentity();
      showNotice(session.profile === "demo"
        ? "Connected to the explicit synthetic CRM profile. These observations do not validate Salesforce or MuleSoft."
        : "Connected to the provider profile. The selected profile alone does not prove a completed Salesforce/MuleSoft integration.", "info");
      await refresh({ quiet: true });
    } catch (error) {
      if (currentEpoch === epoch) showNotice(errorMessage(error), "error");
    } finally {
      $("connect-button").disabled = false;
      $("access-token").value = "";
    }
  });
  $("disconnect-button").addEventListener("click", () => disconnect());
  $("new-nav").addEventListener("click", showNewRequest);
  $("new-top").addEventListener("click", showNewRequest);
  $("close-request").addEventListener("click", closeNewRequest);
  $("queue-nav").addEventListener("click", closeNewRequest);
  $("refresh").addEventListener("click", () => refresh());
  $("search").addEventListener("input", renderQueue);
  document.querySelectorAll("[data-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      filter = button.dataset.filter;
      document.querySelectorAll("[data-filter]").forEach((item) => {
        item.classList.toggle("active", item === button);
        item.setAttribute("aria-pressed", String(item === button));
      });
      renderQueue();
    });
  });
  $("request-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!hasRole("requester") || actionRunning) return;
    const currentEpoch = epoch;
    const request = {
      schema_version: "1.0", message_id: $("message-id").value.trim(),
      customer_reference: $("customer-reference").value.trim() || null,
      order_reference: $("order-reference").value.trim() || null,
      requested_date: $("requested-date").value || null,
      message: $("request-note").value,
    };
    actionRunning = true;
    $("submit-request").disabled = true;
    try {
      const item = await api("/api/v1/cases", { method: "POST", data: request });
      if (currentEpoch !== epoch) return;
      closeNewRequest();
      $("message-id").value = "";
      $("request-note").value = "";
      renderDetail(item);
      showNotice(`Request accepted as case ${item.id}. Waiting for the worker to prepare the proposal.`, "success");
    } catch (error) {
      if (currentEpoch === epoch) showNotice(`${errorMessage(error)}${!error.status
        ? " Submission may have reached the service. Refresh the queue; resend the same message ID if needed." : ""}`, "error");
    } finally {
      actionRunning = false;
      $("submit-request").disabled = false;
      if (currentEpoch === epoch) await refresh({ quiet: true });
    }
  });
  $("approve").addEventListener("click", () => recordDecision("approve"));
  $("reject").addEventListener("click", () => recordDecision("reject"));
  $("reconcile").addEventListener("click", async () => {
    if (!selected || !hasRole("operator") || actionRunning) return;
    const currentEpoch = epoch;
    const id = selected.id;
    actionRunning = true;
    $("reconcile").disabled = true;
    try {
      const result = await api(`/api/v1/cases/${encodeURIComponent(id)}/reconcile`, { method: "POST", data: {} });
      if (currentEpoch !== epoch) return;
      renderDetail(result);
      showNotice("Current system state was read and recorded. No remote mutation was requested.", "info");
    } catch (error) {
      if (currentEpoch === epoch) showNotice(errorMessage(error), "error");
    } finally {
      actionRunning = false;
      if (currentEpoch === epoch && selected) renderReadback(selected);
    }
  });
  setInterval(() => {
    if (!document.hidden && session) refresh({ quiet: true });
  }, 4000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && session) refresh({ quiet: true });
  });
  renderQueue();
})();
