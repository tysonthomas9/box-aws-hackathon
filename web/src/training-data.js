import "./versions.css";
let controller;
const node = (tag, text, cls) => {
  const el = document.createElement(tag);
  if (text != null) el.textContent = text;
  if (cls) el.className = cls;
  return el;
};
export function closeTrainingData() {
  controller?.abort();
  controller = null;
  document.getElementById("training-data-viewer")?.replaceChildren();
}
export function showTrainingData(api, versionId) {
  closeTrainingData();
  const host = document.getElementById("training-data-viewer");
  const heading = node("div", null, "heading");
  const title = node("h2", "Training data · " + versionId);
  const close = node("button", "Close training data");
  close.onclick = closeTrainingData;
  heading.append(title, close);
  const description = node(
    "p",
    "Training questions and answers only. Evaluation questions and answers are never shown.",
    "subtle",
  );
  const form = node("form", null, "training-filters");
  const kind = node("select");
  kind.setAttribute("aria-label", "Training category");
  for (const value of [
    "",
    "fact",
    "procedure",
    "unknown",
    "near_miss",
    "replay",
  ]) {
    const option = node(
      "option",
      value ? value.replaceAll("_", " ") : "All categories",
    );
    option.value = value;
    kind.append(option);
  }
  const search = node("input");
  search.type = "search";
  search.maxLength = 200;
  search.placeholder = "Search training questions and answers";
  search.setAttribute("aria-label", "Search training rows");
  const submit = node("button", "Search training data");
  submit.type = "submit";
  form.append(kind, search, submit);
  const status = node("p");
  status.setAttribute("role", "status");
  const summary = node("div"),
    rows = node("div"),
    nav = node("div", null, "actions");
  const previous = node("button", "Previous training page"),
    next = node("button", "Next training page");
  nav.append(previous, next);
  host.append(heading, description, form, status, summary, rows, nav);
  let page = 1;
  async function load() {
    controller?.abort();
    const current = new AbortController();
    controller = current;
    status.textContent = "Loading verified training data…";
    previous.disabled = next.disabled = submit.disabled = true;
    try {
      const query = new URLSearchParams({
        page: String(page),
        q: search.value,
      });
      if (kind.value) query.set("kind", kind.value);
      const data = await api(
        `versions/${encodeURIComponent(versionId)}/training-rows?${query}`,
        undefined,
        { signal: current.signal },
      );
      if (current.signal.aborted) return;
      status.textContent = `${data.total} matching rows · page ${data.page} of ${Math.max(1, Math.ceil(data.total / data.page_size))}`;
      summary.replaceChildren();
      rows.replaceChildren();
      for (const [name, count] of Object.entries(data.counts))
        summary.append(
          node("span", `${name.replaceAll("_", " ")}: ${count}`, "badge"),
        );
      const audit = node("details");
      audit.append(
        node("summary", "Recipe deviations and audit hashes"),
        node(
          "pre",
          JSON.stringify(
            {
              total_training_rows: data.total_training_rows,
              manifest_sha256: data.manifest_sha256,
              train_sha256: data.train_sha256,
              snapshot_sha256: data.snapshot_sha256,
              audit_sha256: data.audit_sha256,
              recipe_deviations: data.recipe_deviations,
              uncovered_item_count: data.uncovered_item_count,
            },
            null,
            2,
          ),
        ),
      );
      summary.append(audit);
      for (const row of data.rows) {
        const card = node("article", null, "training-example");
        card.append(
          node(
            "span",
            `${row.index} · ${row.kind.replaceAll("_", " ")}`,
            "badge",
          ),
          node("h3", row.question),
          node("pre", row.answer),
        );
        for (const source of row.sources) {
          const link = node(
            "a",
            `Box file ${source.file_id} · version ${source.version_id}`,
          );
          link.href =
            "https://app.box.com/file/" + encodeURIComponent(source.file_id);
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          card.append(link);
        }
        if (!row.sources.length)
          card.append(
            node("p", "No source-file lineage for this row.", "subtle"),
          );
        rows.append(card);
      }
      previous.disabled = page === 1;
      next.disabled = page * data.page_size >= data.total;
    } catch (error) {
      if (!current.signal.aborted) {
        rows.replaceChildren();
        status.textContent = error.message;
      }
    } finally {
      if (!current.signal.aborted) submit.disabled = false;
    }
  }
  form.onsubmit = (event) => {
    event.preventDefault();
    page = 1;
    load();
  };
  kind.onchange = () => {
    page = 1;
    load();
  };
  previous.onclick = () => {
    page -= 1;
    load();
  };
  next.onclick = () => {
    page += 1;
    load();
  };
  load();
  host.scrollIntoView({ block: "start" });
}
