import { test, expect } from "@playwright/test";
import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { resolve, extname } from "node:path";

let server, baseURL;
const dist = resolve(import.meta.dirname, "../dist");
const artifacts = resolve(
  import.meta.dirname,
  "../../.intent/artifacts/results",
);
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

const modes = ["without", "with", "search"];
const categories = [
  "trained_fact",
  "trained_procedure",
  "two_fact",
  "rule_in_question",
  "untold",
  "unrelated",
  "near_miss",
  "in_documents_not_trained",
];
const report = {
  id: "medical-hidden",
  model_version_id: "medical-partial-v1",
  split: "hidden",
  question_set_sha256: "a".repeat(64),
  counts: Object.fromEntries(
    modes.map((mode) => [mode, { fact: { correct: 3, total: 4 } }]),
  ),
  medical_counts: Object.fromEntries(
    modes.map((mode) => [
      mode,
      Object.fromEntries(
        categories.map((category) => [
          category,
          { correct: 2, total: 4, declined: 1, invented: 1 },
        ]),
      ),
    ]),
  ),
  diagnostics: Object.fromEntries(
    modes.map((mode) => [
      mode,
      {
        criteria: { passed: 15, total: 20, pass_rate: 0.75 },
        in_documents_not_trained: {
          correct: 2,
          declined: 1,
          invented: 1,
          total: 4,
        },
        invented_answers: { total: 3, answers: 32, on_untold: 1 },
      },
    ]),
  ),
  paired: Object.fromEntries(
    ["without_vs_with", "without_vs_search", "with_vs_search"].map((pair) => [
      pair,
      { both_correct: 10, left_only: 2, right_only: 5, both_wrong: 15 },
    ]),
  ),
  caveats: ["Synthetic medical corpus; source-document evaluation."],
  overlap_audit: { passed: true },
};
const version = {
  id: report.model_version_id,
  status: "promoted",
  manifest: {
    config: {
      partial_training_key: "training/partial-inputs/frozen.json",
      partial_training_counts: {
        fact: 1473,
        procedure: 56,
        unknown: 247,
        replay: 100,
      },
    },
    training_row_counts: {
      fact: 1473,
      procedure: 56,
      unknown: 247,
      replay: 100,
    },
  },
};

async function setup(page, data = { reports: [report], versions: [version] }) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    expect(url.origin).toBe(baseURL);
    if (!url.pathname.startsWith("/api/")) return route.continue();
    const path = url.pathname.slice(5);
    const models = Object.fromEntries(
      modes.map((mode) => [
        mode,
        {
          version_id: mode === "with" ? version.id : "base",
          arn: "test-model",
          snapshot_sha256: "b".repeat(64),
        },
      ]),
    );
    if (path === "session")
      return route.fulfill({ json: { csrf_token: "fixture" } });
    if (path === "serving")
      return route.fulfill({
        json: { models, stale: false, snapshot_sha256: "b".repeat(64) },
      });
    if (path === "training")
      return route.fulfill({
        json: { versions: [version], control: { locked: false, progress: {} } },
      });
    if (path === "results") return route.fulfill({ json: data });
    if (path === "ask")
      return route.fulfill({
        json: {
          jobs: modes.map((mode) => ({
            id: mode,
            mode,
            status: "succeeded",
            answer: "Fixture answer",
            model_version_id: models[mode].version_id,
            snapshot_sha256: "b".repeat(64),
            latency_ms: 120600,
            queue_ms: 8000,
            retrieval_ms: 110000,
            generation_ms: 2600,
            citations: [],
          })),
          unavailable: [],
        },
      });
    throw Error(`Unexpected API ${path}`);
  });
  await page.goto(baseURL);
  return errors;
}

test("medical results expose all aggregate evidence and recipe deviations", async ({
  page,
}) => {
  const errors = await setup(page);
  await page.getByRole("button", { name: "Results", exact: true }).click();
  const results = page.locator("#reports");
  await expect(
    results.getByText("Sealed hidden set", { exact: true }),
  ).toBeVisible();
  await expect(
    results.getByRole("heading", { name: "Medical question categories" }),
  ).toBeVisible();
  await expect(
    results.getByRole("cell", {
      name: "in documents not trained",
      exact: true,
    }),
  ).toHaveCount(3);
  await expect(
    results.getByRole("cell", { name: "15 / 20 · 75.0%", exact: true }),
  ).toHaveCount(3);
  for (const pair of [
    "Without learning vs Trained",
    "Without learning vs Search",
    "Trained vs Search",
  ])
    await expect(
      results.getByRole("cell", { name: pair, exact: true }),
    ).toBeVisible();
  await expect(
    results.getByText(/near-miss training rows omitted/),
  ).toBeVisible();
  await page.screenshot({
    path: resolve(artifacts, "medical-results.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: resolve(artifacts, "medical-results-mobile.png"),
    fullPage: false,
  });
  await results
    .getByRole("heading", { name: "Paired comparisons", exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: resolve(artifacts, "medical-results-mobile-pairs.png"),
    fullPage: false,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("older reports show missing evidence honestly and keep dev separate", async ({
  page,
}) => {
  const errors = await setup(page, {
    reports: [
      {
        id: "legacy",
        model_version_id: "old",
        split: "dev",
        scores: { with: { fact: 0.5 } },
      },
    ],
    versions: [],
  });
  await page.getByRole("button", { name: "Results", exact: true }).click();
  await expect(
    page.locator("#reports").getByText("Dev set", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Medical category counts not recorded for this report."),
  ).toBeVisible();
  await expect(
    page.getByText("Three-way outcomes not recorded for this report."),
  ).toBeVisible();
  await expect(page.getByText("Version recipe not available.")).toBeVisible();
  expect(errors).toEqual([]);
});

test("answer cards show the long total wait rather than generation alone", async ({
  page,
}) => {
  const errors = await setup(page);
  await page.getByRole("button", { name: "Show Search", exact: true }).click();
  await page.getByRole("textbox").fill("Who handles support?");
  await page.getByRole("button", { name: /Compare/ }).click();
  await expect(page.getByText(/120.60 seconds total/)).toHaveCount(3);
  await expect(
    page.getByText(/Queue 8.00 s · Retrieval 110.00 s · Generation 2.60 s/),
  ).toHaveCount(3);
  await page.screenshot({
    path: resolve(artifacts, "answer-total-latency.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
