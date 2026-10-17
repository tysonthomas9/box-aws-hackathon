import { test, expect } from "@playwright/test";
import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { resolve, extname } from "node:path";

let server, baseURL;
const dist = resolve(import.meta.dirname, "../dist");
const artifacts = resolve(import.meta.dirname, "../../.intent/artifacts/ui3");
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

async function setup(page) {
  const now = Math.floor(Date.now() / 1000);
  const review = (id, file) => ({
    id,
    item_id: id,
    source_file_id: file,
    source_version_id: "2",
    reasons: ["review_all"],
    candidate: {
      subject: "Guidance " + id,
      statement: "Check the source before acting.",
      supporting_quote: "Check the source before acting.",
      trigger_conditions: [],
      steps: [],
    },
  });
  const f = {
    reviews: [review("r1", "42"), review("r2", "42"), review("r3", "99")],
    calls: [],
    errors: [],
    locked: false,
    expired: false,
    version: null,
    failDecision: null,
    trainingError: false,
    sourcesError: false,
    signedIn: true,
    trainedVersion: "trained-v1",
  };
  page.on("pageerror", (error) => f.errors.push(error.message));
  await page.route("**/*", async (route) => {
    const req = route.request(),
      url = new URL(req.url());
    expect(url.origin).toBe(baseURL);
    if (!url.pathname.startsWith("/api/")) return route.continue();
    const path = url.pathname.slice(5),
      body = req.postData() ? req.postDataJSON() : undefined;
    f.calls.push({ path, body });
    const reply = (json, status = 200) => route.fulfill({ json, status });
    if (path === "session") return reply({ csrf_token: "test-csrf" });
    if (!f.signedIn) return reply({ detail: "Sign in to continue" }, 401);
    if (req.method() === "POST")
      expect(req.headers()["x-csrf-token"]).toBe("test-csrf");
    if (path === "logout") {
      f.signedIn = false;
      return reply({});
    }
    if (path === "sources") {
      if (f.sourcesError) return reply({ detail: "Service unavailable" }, 503);
      const waiting = f.reviews.filter((r) => r.source_file_id === "42").length;
      return reply({
        files: [
          {
            file_id: "42",
            name: "Operations guide.txt",
            version_id: "2",
            waiting_review: waiting,
          },
        ],
        events: [
          {
            event_id: "pending",
            received_at: now,
            event_type: "FILE.UPLOADED",
            pending: true,
          },
        ],
        runs: [
          {
            id: "new",
            trigger: "webhook",
            started_at: now,
            status: "completed",
            changes: 2,
            extraction_calls: 1,
            duration_ms: 4500,
            webhook: { received_at: now - 10, event_type: "FILE.UPLOADED" },
            changed_files: [
              {
                file_id: "42",
                name: "Operations guide.txt",
                version_id: "2",
                action: "updated",
                items_extracted: 2,
                waiting_review: waiting,
              },
              {
                file_id: "43",
                name: "training.json",
                version_id: "1",
                action: "skipped",
                items_extracted: 0,
                error: "Non-document export",
                waiting_review: 0,
              },
            ],
          },
          {
            id: "old",
            trigger: "schedule",
            started_at: now - 600,
            status: "completed",
            changes: 0,
          },
        ],
      });
    }
    if (path === "reviews") return reply({ mode: "all", reviews: f.reviews });
    if (path.startsWith("reviews/")) {
      const id = path.slice(8);
      if (id === f.failDecision)
        return reply({ detail: "Request conflicts with current state" }, 409);
      f.reviews = f.reviews.filter((r) => r.id !== id);
      return reply({});
    }
    if (path === "training") {
      if (f.trainingError) return reply({ detail: "Service unavailable" }, 503);
      return reply({
        versions: f.version ? [f.version] : [],
        control: {
          locked: f.locked,
          owner: f.locked ? "trained-v2" : null,
          expired: f.expired,
          progress: { "trained-v2": { helper_spend_usd: 1.23 } },
        },
      });
    }
    if (path === "train") {
      f.version = {
        id: "trained-v2",
        status: "pending",
        manifest: {
          created_at: now,
          config: { estimated_training_usd: 2, max_runtime_seconds: 2400 },
        },
      };
      f.locked = true;
      return reply(f.version);
    }
    if (path === "serving")
      return reply({
        models: {
          without: {
            version_id: "base-v1",
            arn: "base",
            snapshot_sha256: "a".repeat(64),
          },
          with: {
            version_id: f.trainedVersion,
            arn: "trained",
            snapshot_sha256: "a".repeat(64),
          },
          search: null,
        },
        stale: false,
      });
    if (path === "results")
      return reply({ reports: [], versions: f.version ? [f.version] : [] });
    throw Error("Unmocked route " + path);
  });
  await page.goto(baseURL);
  await expect(
    page.getByRole("heading", { name: "Ask Halvard." }),
  ).toBeVisible();
  return f;
}

test("Sources live feed → filtered file approval → training stages → automatic Chat promotion", async ({
  page,
}) => {
  await page.clock.install();
  const f = await setup(page);
  await expect(page.getByRole("navigation").getByRole("button")).toHaveText([
    "Chat",
    "Sources",
    "Review",
    "Training",
    "Results",
  ]);
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Sync now", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText("Non-document export")).toBeVisible();
  await expect(
    page.getByText("File details not recorded for this older run."),
  ).toBeVisible();
  await expect(page.getByText(/webhook received/)).toBeVisible();
  await shot(page, "sources");
  const before = f.calls.filter((c) => c.path === "sources").length;
  await page.clock.fastForward(5100);
  await expect
    .poll(() => f.calls.filter((c) => c.path === "sources").length)
    .toBeGreaterThan(before);
  await page
    .getByRole("link", { name: "2 waiting in Review", exact: true })
    .first()
    .click();
  await expect(page.getByText("Showing Box file 42")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Guidance r3", exact: true }),
  ).toHaveCount(0);
  await shot(page, "review");
  await page
    .getByRole("button", { name: "Approve all from this file", exact: true })
    .click();
  await expect(page.getByText("No items need review.")).toBeVisible();
  expect(
    f.calls.filter((c) => c.path.startsWith("reviews/")).map((c) => c.path),
  ).toEqual(["reviews/r1", "reviews/r2"]);
  await page
    .getByRole("button", { name: "Show all files", exact: true })
    .click();
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(page.getByText("No items need review.")).toBeVisible();
  await page.getByRole("button", { name: "Training", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Train now", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Train now", exact: true }).click();
  await expect(
    page.getByText("Generating training examples", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Train now", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText("$1.23 · generation helpers only", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Not reported by the pipeline", { exact: true }),
  ).toBeVisible();
  await shot(page, "training");
  for (const status of ["training", "importing", "evaluating"]) {
    f.version.status = status;
    await page.clock.fastForward(15100);
    await expect(page.locator(".training-run .badge")).toHaveText(
      status[0].toUpperCase() + status.slice(1),
    );
  }
  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await expect(page.locator(".thread-heading.mode-with")).toContainText(
    "trained-v1",
  );
  f.version.status = "promoted";
  f.locked = false;
  f.trainedVersion = "trained-v2";
  await page.clock.fastForward(15100);
  await expect(page.locator(".thread-heading.mode-with")).toContainText(
    "trained-v2",
  );
  await shot(page, "chat-promoted");
  await page.getByRole("button", { name: "Results", exact: true }).click();
  await expect(page.getByText("No evaluation reports yet.")).toBeVisible();
  await shot(page, "results");
  expect(f.errors).toEqual([]);
  expect(f.calls.filter((c) => c.path === "train")).toHaveLength(1);
});

test("bulk approval reports partial success and leaves remaining items visible", async ({
  page,
}) => {
  const f = await setup(page);
  f.failDecision = "r2";
  await page.getByRole("button", { name: "Review", exact: true }).click();
  await page
    .getByRole("button", { name: "Approve all from this file", exact: true })
    .first()
    .click();
  await expect(page.locator("#notice")).toContainText("Approved 1 of 2 items");
  await expect(
    page.getByRole("heading", { name: "Guidance r2", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Guidance r1", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Approve", exact: true }).first(),
  ).toBeEnabled();
});

test("expired lock with no version stays disabled; status failure is safe and recovers", async ({
  page,
}) => {
  await page.clock.install();
  const f = await setup(page);
  f.locked = true;
  f.expired = true;
  await page.getByRole("button", { name: "Training", exact: true }).click();
  await expect(
    page.getByText(/This lock needs operator recovery/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Train now", exact: true }),
  ).toBeDisabled();
  f.trainingError = true;
  await page.clock.fastForward(15100);
  await expect(page.getByText(/Training status unavailable/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Train now", exact: true }),
  ).toBeDisabled();
  f.trainingError = false;
  f.locked = false;
  await page.clock.fastForward(15100);
  await expect(
    page.getByRole("button", { name: "Train now", exact: true }),
  ).toBeEnabled();
  expect(f.calls.filter((c) => c.path === "train")).toHaveLength(0);
});

test("Sources retries errors, stops polling off-tab and sign-out stops all refreshes", async ({
  page,
}) => {
  await page.clock.install();
  const f = await setup(page);
  f.sourcesError = true;
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  await expect(
    page.getByText("Service unavailable. Retrying automatically.", {
      exact: true,
    }),
  ).toBeVisible();
  f.sourcesError = false;
  await page.clock.fastForward(5100);
  await expect(page.getByText("Non-document export")).toBeVisible();
  await page.getByRole("button", { name: "Review", exact: true }).click();
  const before = f.calls.filter((c) => c.path === "sources").length;
  await page.clock.fastForward(15100);
  expect(f.calls.filter((c) => c.path === "sources")).toHaveLength(before);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByLabel("Demo password")).toBeVisible();
  const allBefore = f.calls.length;
  await page.clock.fastForward(31000);
  expect(f.calls).toHaveLength(allBefore);
  expect(f.errors).toEqual([]);
});

test("all workflow pages fit a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page);
  for (const name of ["Sources", "Review", "Training", "Results", "Chat"]) {
    await page.getByRole("button", { name, exact: true }).click();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
});
