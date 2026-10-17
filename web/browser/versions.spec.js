import { test, expect } from "@playwright/test";
import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { resolve, extname } from "node:path";
let server, baseURL;
const dist = resolve(import.meta.dirname, "../dist");
const artifacts = resolve(import.meta.dirname, "../../.intent/artifacts/ui4");
test.beforeAll(async () => {
  await mkdir(artifacts, { recursive: true });
  server = createServer(async (req, res) => {
    try {
      const path = resolve(
        dist,
        "." +
          new URL(req.url, "http://local").pathname.replace(
            /\/$/,
            "/index.html",
          ),
      );
      if (!path.startsWith(dist + "/")) throw Error("Invalid path");
      const data = await readFile(path);
      res.writeHead(200, {
        "Content-Type":
          {
            ".html": "text/html",
            ".js": "text/javascript",
            ".css": "text/css",
          }[extname(path)] ?? "text/plain",
      });
      res.end(data);
    } catch {
      res.writeHead(404);
      res.end();
    }
  });
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  baseURL = `http://127.0.0.1:${server.address().port}`;
});
test.afterAll(async () => {
  await new Promise((done) => server.close(done));
});
const shot = (page, name) =>
  page.screenshot({ path: resolve(artifacts, name + ".png"), fullPage: true });
const hash = "a".repeat(64);
function fixture() {
  const version = (id, state, extra = {}) => ({
    id,
    state,
    import_arn: state === "loaded" ? "arn:import/" + id : null,
    status: id === "v1" ? "rejected" : "promoted",
    created_at: 1792250000,
    snapshot_sha256: hash,
    dev_score: { candidate: { correct: 18, total: 24 } },
    can_load: state === "not_loaded",
    can_unload: id === "v1",
    ...extra,
  });
  return {
    calls: [],
    errors: [],
    load_active: false,
    slots_used: 3,
    slot_limit: 3,
    default_version_id: "v2",
    versions: [
      version("v2", "loaded"),
      version("v1", "loaded"),
      version("Halvard POC, temporary", "loaded", { status: "temporary" }),
      version("v3", "not_loaded", { status: "rejected" }),
    ],
  };
}
async function setup(page) {
  const f = fixture();
  const model = (id) => ({
    version_id: id,
    arn: "arn:import/" + id,
    snapshot_sha256: hash,
  });
  page.on("pageerror", (e) => f.errors.push(e.message));
  await page.route("**/*", async (route) => {
    const req = route.request(),
      url = new URL(req.url());
    expect(url.origin).toBe(baseURL);
    if (!url.pathname.startsWith("/api/")) return route.continue();
    const path = decodeURIComponent(url.pathname.slice(5));
    const body = req.postData() ? req.postDataJSON() : undefined;
    f.calls.push({ path, body, query: url.search });
    const reply = (json, status = 200) => route.fulfill({ json, status });
    if (path === "session") return reply({ csrf_token: "test-csrf" });
    if (req.method() === "POST")
      expect(req.headers()["x-csrf-token"]).toBe("test-csrf");
    if (path === "versions") return reply(f);
    if (path === "serving")
      return reply({
        models: {
          without: model("base"),
          with: model("v2"),
          search: model("base"),
        },
        approved_snapshot_sha256: hash,
        stale: false,
      });
    if (path === "training")
      return reply({
        versions: f.versions
          .filter((v) => v.status !== "temporary")
          .map((v) => ({
            id: v.id,
            status: v.status,
            manifest: { manifest_hash: hash, created_at: v.created_at },
          })),
        control: { locked: false, progress: {} },
      });
    if (path.endsWith("/training-rows")) {
      let rows = Array.from({ length: 30 }, (_, i) => ({
        index: i + 1,
        kind: i < 28 ? "fact" : "replay",
        question: `Training question ${i + 1}?`,
        answer: `Approved answer ${i + 1}. <script>literal</script>`,
        sources: i < 28 ? [{ file_id: "42", version_id: "7" }] : [],
      }));
      const kind = url.searchParams.get("kind"),
        q = url.searchParams.get("q")?.toLowerCase() ?? "";
      if (kind) rows = rows.filter((r) => r.kind === kind);
      if (q)
        rows = rows.filter((r) =>
          (r.question + r.answer).toLowerCase().includes(q),
        );
      const page = Number(url.searchParams.get("page") || 1);
      return reply({
        version_id: path.split("/")[1],
        rows: rows.slice((page - 1) * 25, page * 25),
        page,
        page_size: 25,
        total: rows.length,
        total_training_rows: 30,
        counts: { fact: 28, replay: 2 },
        manifest_sha256: hash,
        train_sha256: hash,
        snapshot_sha256: hash,
        audit_sha256: hash,
        recipe_deviations: { near_miss_omitted: true },
        uncovered_item_count: 0,
      });
    }
    if (path.endsWith("/unload")) {
      const version = f.versions.find((v) => v.id === path.split("/")[1]);
      version.state = "not_loaded";
      version.import_arn = null;
      version.can_unload = false;
      version.can_load = true;
      f.slots_used -= 1;
      return reply({ id: version.id, state: "not_loaded" });
    }
    if (path.endsWith("/load")) {
      const version = f.versions.find((v) => v.id === path.split("/")[1]);
      version.state = "loading";
      version.can_load = false;
      f.load_active = true;
      return reply({ id: version.id, state: "loading" }, 202);
    }
    if (path === "ask")
      return reply(
        {
          jobs: ["without", "with", "search"].map((mode) => ({
            id: mode,
            mode,
            status: "succeeded",
            model_version_id: mode === "with" ? body.version_id : "base",
            model_arn: "test",
            snapshot_sha256: hash,
            answer:
              f.sourceAnswers?.[mode] ??
              (mode === "with"
                ? `Answer from ${body.version_id}`
                : "Original answer"),
            citations: [],
            expires_at: Math.floor(Date.now() / 1000) + 900,
          })),
          unavailable: [],
          errors: {},
        },
        202,
      );
    if (path === "warm-up")
      return reply(
        {
          jobs: [
            {
              id: "warm",
              mode: "without",
              status: "warming",
              model_version_id: "base",
              model_arn: "test",
              snapshot_sha256: hash,
              expires_at: Math.floor(Date.now() / 1000) + 900,
              warm_up_models: [
                { model_version_id: body.version_id, model_arn: "test" },
              ],
            },
          ],
          unavailable: [],
        },
        202,
      );
    if (path === "jobs/warm")
      return reply({
        id: "warm",
        mode: "without",
        status: "warming",
        model_version_id: "base",
        model_arn: "test",
        snapshot_sha256: hash,
        expires_at: Math.floor(Date.now() / 1000) + 900,
      });
    if (path === "results") return reply({ reports: [], versions: [] });
    throw Error("Unexpected API route " + path);
  });
  await page.goto(baseURL);
  await expect(
    page.getByLabel("Trained version", { exact: true }),
  ).toBeEnabled();
  return f;
}
async function ask(page, text = "Which approved value applies?") {
  await page.getByLabel("Your question").fill(text);
  await page
    .getByRole("button", { name: "Compare answers", exact: true })
    .click();
}

test("selection persists only in this tab and each answer keeps its requested model", async ({
  page,
}) => {
  const f = await setup(page);
  await page.getByLabel("Trained version", { exact: true }).selectOption("v1");
  await ask(page);
  await expect(page.locator(".mode-with .answer-text")).toHaveText(
    "Answer from v1",
  );
  expect(f.calls.find((c) => c.path === "ask").body.version_id).toBe("v1");
  await page.getByLabel("Trained version", { exact: true }).selectOption("v2");
  await ask(page, "A second question?");
  await expect(page.locator(".mode-with .answer-text")).toHaveText([
    "Answer from v1",
    "Answer from v2",
  ]);
  await expect(page.locator(".thread-heading.mode-with .poc-label")).toHaveText(
    "v2",
  );
  await page.getByLabel("Trained version", { exact: true }).selectOption("v1");
  await page.reload();
  await expect(page.getByLabel("Trained version", { exact: true })).toHaveValue(
    "v1",
  );
  await shot(page, "version-picker");
  const other = await page.context().newPage();
  await setup(other);
  await expect(
    other.getByLabel("Trained version", { exact: true }),
  ).toHaveValue("");
  await expect(
    other.locator(".thread-heading.mode-with .poc-label"),
  ).toHaveText("v2");
  await other.close();
  expect(f.errors).toEqual([]);
});

test("full slots require an explicit unload choice, then show loading and cold warming", async ({
  page,
}) => {
  await page.clock.install();
  const f = await setup(page);
  await page.getByLabel("Trained version", { exact: true }).selectOption("v3");
  await expect(
    page.getByRole("button", { name: "Compare answers", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByLabel("Version to unload", { exact: true }),
  ).toBeVisible();
  expect(f.calls.some((c) => c.path.endsWith("/unload"))).toBe(false);
  await shot(page, "slots-full");
  await page
    .getByLabel("Version to unload", { exact: true })
    .selectOption("v1");
  await page
    .getByRole("button", { name: "Unload selected version", exact: true })
    .click();
  await expect(
    page.getByLabel("Version to unload", { exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Load version", exact: true }).click();
  await expect(
    page.getByText("Import is loading. This page refreshes automatically.", {
      exact: true,
    }),
  ).toBeVisible();
  await shot(page, "loading-version");
  const v = f.versions.find((v) => v.id === "v3");
  v.state = "loaded";
  v.import_arn = "arn:import/v3";
  f.load_active = false;
  f.slots_used = 3;
  await page.clock.fastForward(15100);
  await expect(
    page.getByRole("button", { name: "Compare answers", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Warm up", exact: true }).click();
  await expect(
    page.getByText("Warming · base, then trained", { exact: true }),
  ).toBeVisible();
  expect(f.calls.find((c) => c.path === "warm-up").body.version_id).toBe("v3");
  expect(f.errors).toEqual([]);
});

test("training viewer pages/searches only training rows and survives status refresh", async ({
  page,
}) => {
  await page.clock.install();
  const f = await setup(page);
  await page.getByRole("button", { name: "Train", exact: true }).click();
  await page
    .locator(".training-run")
    .filter({ has: page.getByRole("heading", { name: "v1", exact: true }) })
    .getByRole("button", { name: "Training data", exact: true })
    .click();
  await expect(page.locator(".training-example")).toHaveCount(25);
  await expect(page.locator(".training-example").first()).toContainText(
    "<script>literal</script>",
  );
  await expect(page.locator("#training-data-viewer script")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Next training page", exact: true })
    .click();
  await expect(page.locator(".training-example")).toHaveCount(5);
  await page.clock.fastForward(15100);
  await expect(
    page.getByText("30 matching rows · page 2 of 2", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Training category", { exact: true })
    .selectOption("replay");
  await expect(page.locator(".training-example")).toHaveCount(2);
  await page
    .getByLabel("Search training rows", { exact: true })
    .fill("answer 30");
  await page
    .getByRole("button", { name: "Search training data", exact: true })
    .click();
  await expect(page.locator(".training-example")).toHaveCount(1);
  await page
    .getByText("Recipe deviations and audit hashes", { exact: true })
    .click();
  await shot(page, "training-data");
  expect(
    f.calls
      .filter((c) => c.path.includes("training-rows"))
      .every((c) => c.path === "versions/v1/training-rows"),
  ).toBe(true);
  expect(f.calls.some((c) => /hidden|sealed|dev\.json/.test(c.path))).toBe(
    false,
  );
  await page
    .getByRole("button", { name: "Close training data", exact: true })
    .click();
  await expect(page.locator(".training-example")).toHaveCount(0);
  expect(f.errors).toEqual([]);
});

test("version controls fit a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page);
  await page.getByLabel("Trained version", { exact: true }).selectOption("v3");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await shot(page, "version-picker-mobile");
});

test("starter group follows selected version and learned labels stay unverified", async ({
  page,
}) => {
  const f = await setup(page);
  await expect(
    page.getByText("Medical (Rubber Ducks)", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "A documented medical company fact",
      exact: true,
    })
    .click();
  await expect(page.getByLabel("Your question")).toHaveValue(/mRNA-4157/);
  await page
    .getByLabel("Trained version", { exact: true })
    .selectOption("Halvard POC, temporary");
  await expect(
    page.getByText("Halvard (Phase 1)", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "A company fact", exact: true })
    .click();
  await expect(page.getByLabel("Your question")).toHaveValue(
    "Which person owns the Kestrel service?",
  );
  f.sourceAnswers = {
    with: "Mira Solven. (Source: kestrel.txt)",
    without: "A recalled value. (Source: notes.docx)",
    search: "Search answer. (Source: keep-search.txt)",
  };
  await ask(page, "Which person owns the Kestrel service?");
  await expect(page.locator(".mode-with .answer-text")).toHaveText(
    "Mira Solven.",
  );
  const chip = page.getByText("Learned from: kestrel.txt · not verified", {
    exact: true,
  });
  await expect(chip).toBeVisible();
  await expect(chip).toHaveAttribute(
    "title",
    "The model recalled this source from training; it is not a retrieved citation",
  );
  await page.locator(".mode-with .raw-model-answer summary").click();
  await expect(page.locator(".mode-with .raw-model-answer pre")).toHaveText(f.sourceAnswers.with);
  await expect(
    page.getByText("Learned from: notes.docx · not verified", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Show Search", exact: true }).click();
  await expect(page.locator(".mode-search .answer-text")).toHaveText(
    f.sourceAnswers.search,
  );
  await expect(page.locator(".mode-search .learned-source-chip")).toHaveCount(
    0,
  );
  await shot(page, "learned-sources-halvard");
  await page.getByLabel("Trained version", { exact: true }).selectOption("v2");
  await expect(
    page.getByText("Medical (Rubber Ducks)", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "A company fact", exact: true }),
  ).toHaveCount(0);
  expect(f.errors).toEqual([]);
});
