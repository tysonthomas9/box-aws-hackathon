import { mountAsk, unmountAsk } from "./src/ask.jsx";
import { retryAfterMs } from "./src/polling.js";
import { modeLabel, reportDiagnostics, recipeDetails } from "./src/results.js";
import "./style.css";
("use strict");
const $ = (id) => document.getElementById(id);
let csrf = "",
  active = "ask",
  trainingTimer,
  sourcesTimer,
  sourcesRequest = 0,
  trainingRequest = 0,
  signedIn = false,
  trainingBusy = true,
  trainingSubmitting = false,
  reviewFilter = null;
const node = (tag, text, cls) => {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
};
const message = (text) => {
  $("notice").textContent = text;
};
async function api(path, body, options = {}) {
  const response = await fetch("/api/" + path, {
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    signal: options.signal,
    headers:
      body === undefined
        ? {}
        : { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const value = await response.json();
  if (response.status === 401) {
    showLogin();
    throw Error(value.detail || "Sign in to continue");
  }
  if (!response.ok) {
    const error = Error(value.detail || "Request failed");
    error.data = value;
    error.status = response.status;
    error.retryAfterMs = retryAfterMs(response.headers.get("Retry-After"));
    throw error;
  }
  return value;
}
function showLogin() {
  signedIn = false;
  sourcesRequest += 1;
  trainingRequest += 1;
  unmountAsk();
  clearTimeout(trainingTimer);
  clearTimeout(sourcesTimer);
  csrf = "";
  $("workspace").hidden = true;
  $("login-screen").hidden = false;
  $("logout").hidden = true;
}
function showWorkspace() {
  signedIn = true;
  mountAsk(api);
  $("workspace").hidden = false;
  $("login-screen").hidden = true;
  $("logout").hidden = false;
}
function table(parent, headings, rows) {
  const wrap = node("div", undefined, "table-wrap"),
    t = node("table"),
    head = node("tr");
  for (const h of headings) head.append(node("th", h));
  const thead = node("thead");
  thead.append(head);
  t.append(thead);
  const b = node("tbody");
  for (const row of rows) {
    const tr = node("tr");
    for (const cell of row) {
      const td = node("td");
      td.append(
        cell instanceof Node
          ? cell
          : document.createTextNode(String(cell ?? "—")),
      );
      tr.append(td);
    }
    b.append(tr);
  }
  t.append(b);
  wrap.append(t);
  parent.append(wrap);
  if (!rows.length) parent.append(node("p", "Nothing to show yet.", "subtle"));
}
function sourceLink(id, name) {
  const a = node("a", name || id);
  a.href = "https://app.box.com/file/" + encodeURIComponent(id);
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}
function details(parent, title, value) {
  const d = node("details"),
    s = node("summary", title);
  d.append(s, node("pre", JSON.stringify(value, null, 2)));
  parent.append(d);
}
function reviewLink(fileId, count) {
  const link = node("a", `${count ?? 0} waiting in Review`);
  link.href = "#review?file=" + encodeURIComponent(fileId);
  link.onclick = (event) => {
    event.preventDefault();
    reviewFilter = fileId;
    load("review");
  };
  return link;
}
function eventLabel(type) {
  return (
    {
      "FILE.UPLOADED": "Uploaded / changed",
      "FILE.TRASHED": "Deleted (trashed)",
      "FILE.DELETED": "Deleted",
      "FILE.MOVED": "Moved",
    }[type] ??
    type ??
    "Event type not recorded"
  );
}
async function sources() {
  clearTimeout(sourcesTimer);
  const request = ++sourcesRequest;
  let refreshMs = 5000;
  try {
    const data = await api("sources");
    if (!signedIn || active !== "sources" || request !== sourcesRequest) return;
    $("source-files").replaceChildren();
    table(
      $("source-files"),
      ["Document", "Version", "State", "Review"],
      data.files.map((f) => [
        sourceLink(f.file_id, f.name),
        f.version_id,
        f.retired ? "Retired" : "Active",
        reviewLink(f.file_id, f.waiting_review),
      ]),
    );
    $("webhook-events").replaceChildren();
    const linked = new Set(data.runs.map((r) => r.event_id).filter(Boolean));
    for (const event of data.events ?? []) {
      if (linked.has(event.event_id)) continue;
      const card = node("article", undefined, "webhook-receipt");
      card.append(
        node("span", "Box webhook", "badge"),
        node("strong", eventLabel(event.event_type)),
        node(
          "p",
          `Received ${new Date(event.received_at * 1000).toLocaleString()} · ${event.pending ? "Waiting for sync" : "Reconciled by a sync"}`,
          "subtle",
        ),
      );
      $("webhook-events").append(card);
    }
    $("sync-runs").replaceChildren();
    if (!data.runs.length)
      $("sync-runs").append(
        node(
          "p",
          "No sync runs yet. New Box activity will appear automatically.",
          "panel",
        ),
      );
    for (const run of data.runs) {
      const card = node("article", undefined, "sync-run");
      const trigger =
        { webhook: "Box webhook", schedule: "Schedule", manual: "Manual sync" }[
          run.trigger
        ] ?? run.trigger;
      card.append(
        node("span", trigger, "badge"),
        node("span", run.status, "badge"),
        node("h3", new Date(run.started_at * 1000).toLocaleString()),
      );
      if (run.webhook)
        card.append(
          node(
            "p",
            `${eventLabel(run.webhook.event_type)} · webhook received ${new Date(run.webhook.received_at * 1000).toLocaleString()}`,
            "subtle",
          ),
        );
      else if (run.trigger === "webhook")
        card.append(
          node(
            "p",
            "Webhook receipt details not recorded or expired.",
            "subtle",
          ),
        );
      card.append(
        node(
          "p",
          `${run.changes ?? 0} knowledge changes · ${run.extraction_calls ?? 0} files extracted · ${run.retirement_calls ?? 0} retirements · ${Math.round((run.duration_ms ?? 0) / 1000)} seconds`,
          "subtle",
        ),
      );
      if (run.error_type)
        card.append(
          node(
            "p",
            `Sync failed: ${run.error_type}. Pending work will be retried by the next sync.`,
            "activity-error",
          ),
        );
      if (run.changed_files === undefined)
        card.append(
          node("p", "File details not recorded for this older run.", "subtle"),
        );
      else if (!run.changed_files.length)
        card.append(
          node(
            "p",
            run.status === "running"
              ? "File details appear when this run finishes."
              : "No changed files.",
            "subtle",
          ),
        );
      else
        table(
          card,
          [
            "Document",
            "Version",
            "Change",
            "Items extracted",
            "Review",
            "Details",
          ],
          run.changed_files.map((file) => [
            sourceLink(file.file_id, file.name),
            file.version_id,
            file.action,
            file.action === "retired" ? "—" : (file.items_extracted ?? "—"),
            reviewLink(file.file_id, file.waiting_review),
            file.error ??
              (file.action === "retired"
                ? "Retirement proposals require review"
                : "—"),
          ]),
        );
      if (run.file_details_truncated)
        card.append(
          node(
            "p",
            "Showing the first 50 file changes. Run totals include all files.",
            "subtle",
          ),
        );
      $("sync-runs").append(card);
    }
    $("sync-status").textContent =
      `Live · updated ${new Date().toLocaleTimeString()} · refreshes every 5 seconds`;
  } catch (error) {
    if (error.status === 429)
      refreshMs = Math.max(60000, error.retryAfterMs ?? 0);
    if (signedIn && active === "sources" && request === sourcesRequest)
      $("sync-status").textContent =
        `${error.message}. Retrying automatically.`;
  } finally {
    if (signedIn && active === "sources" && request === sourcesRequest)
      sourcesTimer = setTimeout(sources, refreshMs);
  }
}
async function review() {
  const data = await api("reviews");
  $("review-mode").value = data.mode;
  if (reviewFilter)
    data.reviews = data.reviews.filter(
      (r) => r.source_file_id === reviewFilter,
    );
  $("reviews").replaceChildren();
  if (reviewFilter) {
    const filter = node("div", undefined, "review-filter");
    const clear = node("button", "Show all files");
    clear.onclick = () => {
      reviewFilter = null;
      load("review");
    };
    filter.append(node("p", "Showing Box file " + reviewFilter), clear);
    $("reviews").append(filter);
  }
  if (!data.reviews.length)
    $("reviews").append(node("p", "No items need review.", "panel"));
  const groups = new Map();
  for (const r of data.reviews) {
    if (!groups.has(r.source_file_id)) groups.set(r.source_file_id, []);
    groups.get(r.source_file_id).push(r);
  }
  for (const [fileId, reviews] of groups) {
    const group = node("section", undefined, "review-file");
    const heading = node("div", undefined, "heading");
    const title = node("div");
    title.append(
      sourceLink(fileId, "Box file " + fileId),
      node("p", `${reviews.length} items to review`, "subtle"),
    );
    const approve = node("button", "Approve all from this file");
    approve.onclick = () =>
      run(approve, async () => {
        for (const b of $("reviews").querySelectorAll("button"))
          b.disabled = true;
        let approved = 0;
        try {
          for (const r of reviews) {
            await api("reviews/" + encodeURIComponent(r.id), {
              action: "approve",
            });
            approved += 1;
          }
          message(`Approved ${approved} items from Box file ${fileId}.`);
        } catch (error) {
          message(
            `Approved ${approved} of ${reviews.length} items. ${error.message} Remaining items are still awaiting review.`,
          );
        } finally {
          await review();
        }
      });
    heading.append(title, approve);
    group.append(heading);
    groups.set(fileId, group);
    $("reviews").append(group);
  }
  for (const r of data.reviews) {
    const card = node("article");
    card.append(node("h2", r.candidate.subject));
    for (const reason of r.reasons)
      card.append(node("span", reason.replaceAll("_", " "), "badge stale"));
    card.append(
      node("p", "Previous: " + (r.previous?.statement || "No approved value")),
      node("p", "Proposed: " + r.candidate.statement),
      node("blockquote", r.candidate.supporting_quote),
      sourceLink(r.source_file_id, "Source · version " + r.source_version_id),
    );
    const statement = node("textarea"),
      quote = node("textarea"),
      conditions = node("textarea"),
      steps = node("textarea");
    for (const [label, field, value] of [
      ["Statement", statement, r.candidate.statement],
      ["Supporting quote", quote, r.candidate.supporting_quote],
      [
        "Trigger conditions (one per line)",
        conditions,
        r.candidate.trigger_conditions.join("\n"),
      ],
      ["Steps (one per line)", steps, r.candidate.steps.join("\n")],
    ]) {
      const l = node("label", label);
      field.value = value;
      l.append(field);
      card.append(l);
    }
    const actions = node("div", undefined, "actions");
    for (const action of ["approve", "edit", "reject"]) {
      const b = node(
        "button",
        action === "edit"
          ? "Save edit & approve"
          : action[0].toUpperCase() + action.slice(1),
      );
      b.onclick = () =>
        run(b, async () => {
          const body = { action };
          if (action === "edit")
            body.edited = {
              ...r.candidate,
              statement: statement.value,
              supporting_quote: quote.value,
              trigger_conditions: conditions.value.split("\n").filter(Boolean),
              steps: steps.value.split("\n").filter(Boolean),
            };
          await api("reviews/" + encodeURIComponent(r.id), body);
          await review();
        });
      actions.append(b);
    }
    card.append(actions);
    groups.get(r.source_file_id).append(card);
  }
}
async function training() {
  clearTimeout(trainingTimer);
  if (!signedIn) return;
  const request = ++trainingRequest;
  let data;
  try {
    data = await api("training");
  } catch (error) {
    if (!signedIn || request !== trainingRequest) return;
    trainingBusy = true;
    $("train").disabled = true;
    $("training-status").textContent =
      "Training status unavailable. Train now stays disabled until the lock can be checked.";
    trainingTimer = setTimeout(
      () => training().catch((e) => message(e.message)),
      error.status === 429 ? Math.max(60000, error.retryAfterMs ?? 0) : 15000,
    );
    if (error.status !== 429) throw error;
    return;
  }
  if (!signedIn || request !== trainingRequest) return;
  $("training").replaceChildren();
  const labels = {
    pending: "Generating training examples",
    training: "Training",
    importing: "Importing",
    evaluating: "Evaluating",
    ready: "Awaiting promotion",
    promoted: "Promoted",
    rejected: "Rejected",
    failed: "Failed",
    deleted: "Deleted",
  };
  const versions = [...data.versions].sort(
    (a, b) => (b.manifest?.created_at ?? 0) - (a.manifest?.created_at ?? 0),
  );
  const previousBusy = trainingBusy;
  trainingBusy =
    data.control?.locked !== false ||
    versions.some((v) =>
      ["pending", "training", "importing", "evaluating", "ready"].includes(
        v.status,
      ),
    );
  $("train").disabled = trainingBusy || trainingSubmitting;
  $("training-status").textContent = data.control?.locked
    ? `Training is locked by ${data.control.owner ?? "an active run"}. ${data.control.expired ? "This lock needs operator recovery; it does not unlock automatically." : "Wait for this run to finish before starting another."}`
    : trainingBusy
      ? "Checking the training lock. Train now is unavailable while a run is active or status is unknown."
      : "Ready to train on approved knowledge. Status refreshes automatically.";
  if (!versions.length)
    $("training").append(
      node(
        "p",
        "No training runs yet. Approve knowledge in Review, then choose Train now.",
        "panel",
      ),
    );
  for (const v of versions) {
    const card = node("article", undefined, "training-run");
    card.append(
      node("span", labels[v.status] ?? v.status, "badge"),
      node("h2", v.id),
    );
    const created = v.manifest?.created_at;
    const elapsed = created
      ? Math.max(0, Math.floor((Date.now() / 1000 - created) / 60))
      : null;
    const facts = node("dl", undefined, "run-metrics");
    for (const [label, value] of [
      [
        "ETA",
        ["promoted", "rejected", "failed", "deleted"].includes(v.status)
          ? "Run finished"
          : "Not reported by the pipeline",
      ],
      [
        "Started",
        created ? new Date(created * 1000).toLocaleString() : "Not reported",
      ],
      [
        "Time since start",
        elapsed == null ? "Not reported" : `${elapsed} minutes`,
      ],
    ])
      facts.append(node("dt", label), node("dd", value));
    card.append(facts);
    if (v.manifest?.config?.max_runtime_seconds)
      card.append(
        node(
          "p",
          `GPU runtime limit: ${Math.ceil(v.manifest.config.max_runtime_seconds / 60)} minutes. Generation, import and evaluation take additional time.`,
          "subtle",
        ),
      );
    $("training").append(card);
  }
  if (previousBusy && !trainingBusy)
    window.dispatchEvent(new Event("kloop:ask-open"));
  trainingTimer = setTimeout(
    () => training().catch((e) => message(e.message)),
    15000,
  );
}
async function results() {
  const data = await api("results");
  $("reports").replaceChildren();
  if (!data.reports.length)
    $("reports").append(node("p", "No evaluation reports yet.", "panel"));
  for (const r of data.reports) {
    const card = node("article");
    card.append(
      node(
        "span",
        r.split === "hidden" ? "Sealed hidden set" : "Dev set",
        "badge",
      ),
      node("h2", r.model_version_id),
      node("p", "Question-set hash: " + r.question_set_sha256),
    );
    const rows = [];
    for (const [key, value] of Object.entries(r.scores || {})) {
      if (value !== null && typeof value === "object") {
        for (const [kind, score] of Object.entries(value))
          rows.push([
            modeLabel(key),
            kind,
            typeof score === "number"
              ? (100 * score).toFixed(1) + "%"
              : JSON.stringify(score),
          ]);
      } else
        rows.push([
          key,
          "",
          typeof value === "number" ? (100 * value).toFixed(1) + "%" : value,
        ]);
    }
    if (r.counts && Object.keys(r.counts).length) {
      rows.length = 0;
      for (const [mode, kinds] of Object.entries(r.counts)) {
        for (const [kind, count] of Object.entries(kinds))
          rows.push([
            modeLabel(mode),
            kind,
            count.correct +
              " / " +
              count.total +
              " · " +
              (count.total
                ? ((100 * count.correct) / count.total).toFixed(1) + "%"
                : "—"),
          ]);
      }
    }
    table(card, ["Mode / metric", "Question type", "Score"], rows);
    reportDiagnostics(card, r, { node, table, details });
    recipeDetails(
      card,
      data.versions.find((v) => v.id === r.model_version_id),
      { node, table, details },
    );
    card.append(
      node(
        "p",
        "Overlap check: " +
          (r.overlap_audit?.passed === true
            ? "no detected lexical collisions"
            : r.overlap_audit?.passed === false
              ? "failed"
              : "result not reported"),
      ),
    );
    details(card, "Overlap audit and evaluation bindings", {
      audit: r.overlap_audit,
      bindings: r.bindings,
    });
    details(card, "Counts, gate and caveats", {
      counts: r.counts,
      gate: r.gate,
      caveats: r.caveats,
    });
    $("reports").append(card);
  }
  $("versions").replaceChildren();
  const failed = node("details");
  failed.append(
    node(
      "summary",
      `Failed runs (${data.versions.filter((v) => v.status === "failed").length})`,
    ),
  );
  for (const v of data.versions) {
    const card = node("article");
    card.append(node("h3", v.id + " · " + v.status));
    const hidden = data.reports.find(
      (r) => r.split === "hidden" && r.model_version_id === v.id,
    );
    const scores = [];
    for (const mode of ["without", "with", "search"]) {
      const counts = Object.values(hidden?.counts?.[mode] ?? {});
      if (!counts.length) continue;
      const correct = counts.reduce((sum, count) => sum + count.correct, 0);
      const total = counts.reduce((sum, count) => sum + count.total, 0);
      scores.push(
        `${modeLabel(mode)} ${correct}/${total} (${total ? ((100 * correct) / total).toFixed(1) + "%" : "—"})`,
      );
    }
    card.append(
      node(
        "p",
        `Hidden set: ${scores.length ? scores.join(" · ") : "not evaluated"}`,
      ),
    );
    recipeDetails(card, v, { node, table, details });
    details(card, "Manifest", v.manifest);
    if (v.status === "failed") failed.append(card);
    else $("versions").append(card);
  }
  if (failed.children.length > 1) $("versions").append(failed);
}
async function load(screen) {
  active = screen;
  clearTimeout(sourcesTimer);
  for (const e of document.querySelectorAll(".screen"))
    e.hidden = e.id !== screen;
  for (const b of document.querySelectorAll("[data-screen]")) {
    if (b.dataset.screen === screen) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  }
  message("");
  try {
    await {
      sources,
      review,
      ask: async () => {
        window.dispatchEvent(new Event("kloop:ask-open"));
      },
      "training-screen": training,
      results,
    }[screen]();
  } catch (e) {
    message(e.message);
  }
}
async function run(button, fn) {
  button.disabled = true;
  message("");
  try {
    await fn();
  } catch (e) {
    message(e.message);
  } finally {
    button.disabled =
      button.id === "train" && (trainingBusy || trainingSubmitting);
  }
}
$("login").onsubmit = (e) => {
  e.preventDefault();
  run(e.submitter, async () => {
    const data = await api("login", { password: $("password").value });
    $("password").value = "";
    csrf = data.csrf_token;
    showWorkspace();
    await load(active);
    if (active !== "training-screen") await training();
  });
};
$("logout").onclick = () =>
  run($("logout"), async () => {
    await api("logout", {});
    showLogin();
  });
for (const b of document.querySelectorAll("[data-screen]"))
  b.onclick = () => {
    if (b.dataset.screen === "review") reviewFilter = null;
    load(b.dataset.screen);
  };
$("review-mode").onchange = () =>
  run($("review-mode"), async () => {
    await api("review-mode", { mode: $("review-mode").value });
    await review();
  });
$("train").onclick = () =>
  run($("train"), async () => {
    trainingSubmitting = true;
    const key = sessionStorage.getItem("train-request") || crypto.randomUUID();
    sessionStorage.setItem("train-request", key);
    try {
      await api("train", { request_id: key });
      sessionStorage.removeItem("train-request");
    } finally {
      trainingSubmitting = false;
      await training();
    }
  });
api("session")
  .then((data) => {
    csrf = data.csrf_token;
    showWorkspace();
    return load(active).then(() => training().catch((e) => message(e.message)));
  })
  .catch((e) => {
    showLogin();
    if (!e.message.includes("Sign in")) message(e.message);
  });
