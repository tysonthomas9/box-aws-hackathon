import { mountAsk, unmountAsk } from "./src/ask.jsx";
import { retryAfterMs } from "./src/polling.js";
import "./style.css";
("use strict");
const $ = (id) => document.getElementById(id);
let csrf = "",
  active = "sources",
  trainingTimer,
  trainingBusy = false;
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
  unmountAsk();
  clearTimeout(trainingTimer);
  csrf = "";
  $("workspace").hidden = true;
  $("login-screen").hidden = false;
  $("logout").hidden = true;
}
function showWorkspace() {
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
async function sources() {
  const data = await api("sources");
  $("source-files").replaceChildren();
  table(
    $("source-files"),
    ["Document", "Version", "State"],
    data.files.map((f) => [
      sourceLink(f.file_id, f.name),
      f.version_id,
      f.retired ? "Retired" : "Active",
    ]),
  );
  $("sync-runs").replaceChildren();
  table(
    $("sync-runs"),
    ["Trigger", "Started", "Duration", "Status"],
    data.runs.map((r) => [
      r.trigger,
      new Date(r.started_at * 1000).toLocaleString(),
      r.duration_ms + " ms",
      r.status,
    ]),
  );
}
async function review() {
  const data = await api("reviews");
  $("review-mode").value = data.mode;
  $("reviews").replaceChildren();
  if (!data.reviews.length)
    $("reviews").append(node("p", "No items need review.", "panel"));
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
    $("reviews").append(card);
  }
}
async function training() {
  let data;
  try {
    data = await api("training");
  } catch (error) {
    if (error.status !== 429) throw error;
    clearTimeout(trainingTimer);
    trainingTimer = setTimeout(
      () => training().catch((e) => message(e.message)),
      Math.max(60000, error.retryAfterMs ?? 0),
    );
    return;
  }
  $("training").replaceChildren();
  table(
    $("training"),
    ["Version", "Progress"],
    data.versions.map((v) => [v.id, v.status]),
  );
  const busy = data.versions.some((v) =>
    ["pending", "training", "importing", "evaluating"].includes(v.status),
  );
  trainingBusy = busy;
  $("train").disabled = busy;
  clearTimeout(trainingTimer);
  if (busy)
    trainingTimer = setTimeout(
      () => training().catch((e) => message(e.message)),
      5000,
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
            key,
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
            mode,
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
  for (const v of data.versions) {
    const card = node("article");
    card.append(node("h3", v.id + " · " + v.status));
    details(card, "Manifest", v.manifest);
    $("versions").append(card);
  }
}
async function load(screen) {
  active = screen;
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
        await training();
      },
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
    button.disabled = button.id === "train" && trainingBusy;
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
  });
};
$("logout").onclick = () =>
  run($("logout"), async () => {
    await api("logout", {});
    showLogin();
  });
for (const b of document.querySelectorAll("[data-screen]"))
  b.onclick = () => load(b.dataset.screen);
$("sync").onclick = () =>
  run($("sync"), async () => {
    await api("sync", {});
    message("Sync queued. Refresh Sources shortly to see progress.");
    await sources();
  });
$("review-mode").onchange = () =>
  run($("review-mode"), async () => {
    await api("review-mode", { mode: $("review-mode").value });
    await review();
  });
$("train").onclick = () =>
  run($("train"), async () => {
    const key = sessionStorage.getItem("train-request") || crypto.randomUUID();
    sessionStorage.setItem("train-request", key);
    await api("train", { request_id: key });
    sessionStorage.removeItem("train-request");
    await training();
  });
api("session")
  .then((data) => {
    csrf = data.csrf_token;
    showWorkspace();
    return load(active);
  })
  .catch((e) => {
    showLogin();
    if (!e.message.includes("Sign in")) message(e.message);
  });
