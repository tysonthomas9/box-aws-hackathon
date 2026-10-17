import { test, expect } from "@playwright/test";
import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { resolve, extname } from "node:path";
let server, baseURL;
const dist = resolve(import.meta.dirname, "../dist");
const artifacts = resolve(
  import.meta.dirname,
  "../../.intent/artifacts/openui",
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
      if (!path.startsWith(dist + "/")) throw new Error("invalid path");
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
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  baseURL = `http://127.0.0.1:${server.address().port}`;
});
test.afterAll(async () => {
  await new Promise((resolve) => server.close(resolve));
});
function fixture() {
  const snapshot = "a".repeat(64);
  const models = Object.fromEntries(
    ["without", "with", "search"].map((mode) => [
      mode,
      {
        version_id: mode === "with" ? "trained-v7" : "base-v1",
        arn: `arn:aws:bedrock:us-east-2:000000000000:imported-model/${mode}`,
        snapshot_sha256: snapshot,
      },
    ]),
  );
  const job = (mode) => ({
    id: mode,
    mode,
    status: "queued",
    model_version_id: models[mode].version_id,
    model_arn: models[mode].arn,
    snapshot_sha256: snapshot,
    created_at: Math.floor(Date.now() / 1000),
    expires_at: Math.floor(Date.now() / 1000) + 900,
    citations: [],
    answer: null,
  });
  return { models, snapshot, job };
}
async function setup(page, options = {}) {
  const f = fixture();
  let signedIn = false;
  const calls = [];
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  await page.route("**/*", async (route) => {
    const req = route.request(),
      url = new URL(req.url());
    if (url.origin !== baseURL)
      throw new Error("Unexpected outbound request: " + url.origin);
    if (!url.pathname.startsWith("/api/")) return route.continue();
    const path = url.pathname.slice(5);
    calls.push({ path, method: req.method() });
    const reply = (data, status = 200) => route.fulfill({ status, json: data });
    if (path === "session")
      return reply(
        signedIn
          ? { csrf_token: "fake-csrf" }
          : { detail: "Sign in to continue" },
        signedIn ? 200 : 401,
      );
    if (path === "login") {
      signedIn = true;
      return reply({ csrf_token: "fake-csrf" });
    }
    expect(signedIn).toBe(true);
    if (req.method() === "POST")
      expect(req.headers()["x-csrf-token"]).toBe("fake-csrf");
    if (path === "logout") {
      signedIn = false;
      return reply({});
    }
    if (path === "sources") return reply({ files: [], runs: [] });
    if (path === "reviews") return reply({ mode: "exceptions", reviews: [] });
    if (path === "results") return reply({ reports: [], versions: [] });
    if (path === "serving")
      return reply({
        models: options.unavailable ? { ...f.models, with: null } : f.models,
        approved_snapshot_sha256: f.snapshot,
        stale: true,
      });
    if (path === "training") return reply({ versions: [] });
    if (path === "warm-up")
      return reply(
        {
          jobs: [
            {
              ...f.job("without"),
              id: "warm",
              warm_up: true,
              warm_up_models: ["without", "with"].map((mode) => ({
                model_arn: f.models[mode].arn,
                model_version_id: f.models[mode].version_id,
              })),
            },
          ],
          unavailable: [],
        },
        202,
      );
    if (path === "ask")
      return reply(
        {
          jobs: ["without", "with", "search"]
            .filter((m) => !(options.unavailable && m === "with"))
            .map(f.job),
          errors: {},
          unavailable: options.unavailable ? ["with"] : [],
        },
        202,
      );
    if (path.startsWith("jobs/")) {
      const mode = path.slice(5);
      if (mode === "warm")
        return reply({
          ...f.job("without"),
          id: "warm",
          warm_up: true,
          status: "warming",
          warm_up_models: ["without", "with"].map((mode) => ({
            model_arn: f.models[mode].arn,
            model_version_id: f.models[mode].version_id,
          })),
        });
      const status = options.warming
        ? "warming"
        : options.error && mode === "with"
          ? "failed"
          : "succeeded";
      return reply({
        ...f.job(mode),
        status,
        error:
          status === "failed"
            ? "Model is still warming; use Warm up and try again"
            : null,
        answer:
          status === "succeeded"
            ? {
                without: "I do not know the approved procedure.",
                with: options.longAnswer
                  ? "A long trained answer. ".repeat(100)
                  : "Check the approved guidance first.\n[S1] is a learned source label. <script>test</script>",
                search:
                  "The retrieved guide says to check the environment before replacement. [S1]",
              }[mode]
            : null,
        latency_ms: status === "succeeded" ? 2250 : null,
        citations:
          mode === "search" && status === "succeeded"
            ? [
                {
                  label: "S1",
                  file_id: "42",
                  name: "Approved operations guide.txt",
                  version_id: "9",
                  quote: "Check the environment first, then retest.",
                },
              ]
            : [],
      });
    }
    throw new Error("Unmocked API route: " + path);
  });
  await page.goto(baseURL);
  await expect(page.getByLabel("Demo password")).toBeVisible();
  expect(calls.map((c) => c.path)).toEqual(["session"]);
  await page.getByLabel("Demo password").fill("fake-demo-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await expect(
    page.getByText("Model readiness", { exact: true }),
  ).toBeVisible();
  return { calls, errors };
}
async function ask(page) {
  await page.getByLabel("Your question").fill("What should I check first?");
  await page
    .getByRole("button", { name: "Compare answers", exact: true })
    .click();
}
async function screenshot(page, name) {
  await page.screenshot({ path: resolve(artifacts, name), fullPage: true });
}
test("empty thread, six prompts, warming state and sign-out cancellation", async ({
  page,
}) => {
  const { calls, errors } = await setup(page, { warming: true });
  await expect(
    page.getByRole("heading", { name: "Without learning", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Starter prompts").getByRole("button"),
  ).toHaveCount(6);
  await screenshot(page, "empty-1440.png");
  await page.getByLabel("Starter prompts").getByRole("button").first().click();
  expect(await page.getByLabel("Your question").inputValue()).not.toBe("");
  await page.getByRole("button", { name: "Warm up", exact: true }).click();
  await expect(page.getByText("Warming · base, then trained")).toBeVisible();
  await expect(page.getByText(/Up to 15 minutes/)).toBeVisible();
  await ask(page);
  await expect(
    page.locator(".answer-bubble .badge", { hasText: "Warming" }),
  ).toHaveCount(2);
  await screenshot(page, "warming-1440.png");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByLabel("Demo password")).toBeVisible();
  const before = calls.length;
  await page.clock.install();
  await page.clock.fastForward(5000);
  expect(calls.length).toBe(before);
  await expect(page.locator(".ask-chat")).toHaveCount(0);
  expect(errors.filter((e) => !e.includes("401"))).toEqual([]);
});
test("three completed cards, literal answers, citations, narrow desktop and other screens", async ({
  page,
}) => {
  const { errors } = await setup(page);
  await ask(page);
  await expect(
    page.locator(".answer-bubble .badge", { hasText: "Done" }),
  ).toHaveCount(2);
  await expect(page.locator(".user-question p")).toHaveText([
    "What should I check first?",
    "What should I check first?",
  ]);
  await expect(page.locator(".mode-with .answer-text")).toHaveText(
    "Check the approved guidance first.\n[S1] is a learned source label. <script>test</script>",
  );
  await expect(page.locator(".mode-with a")).toHaveCount(0);
  await screenshot(page, "completed-1440.png");
  await expect(page.locator(".thread-heading")).toHaveCount(2);
  await expect(page.locator(".answer-bubble.mode-search")).toHaveCount(0);
  await page.getByRole("button", { name: "Show Search", exact: true }).click();
  await expect(page.locator(".thread-heading")).toHaveCount(3);
  await expect(page.locator(".answer-bubble.mode-search")).toHaveCount(1);
  await expect(
    page.getByRole("link", { name: /Approved operations guide/ }),
  ).toHaveAttribute("href", "https://app.box.com/file/42");
  await expect(
    page.locator(".thread-heading .model-binding dd", {
      hasText: "a".repeat(64),
    }),
  ).toHaveCount(3);
  await screenshot(page, "search-1440.png");
  await page.setViewportSize({ width: 1280, height: 1100 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const widths = await page
    .locator(".thread-headings .thread-heading")
    .evaluateAll((nodes) => nodes.map((n) => n.getBoundingClientRect().width));
  expect(widths.every((width) => width >= 320)).toBe(true);
  await screenshot(page, "completed-1280.png");
  for (const name of ["Sources", "Review", "Results"]) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(page.locator(`#${name.toLowerCase()}`)).toBeVisible();
  }
  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await expect(page.locator(".answer-bubble")).toHaveCount(3);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors.filter((e) => !e.includes("401"))).toEqual([]);
});
test("per-mode failure keeps the other cards and question", async ({
  page,
}) => {
  await setup(page, { error: true });
  await ask(page);
  await expect(page.locator(".mode-with").getByRole("status")).toHaveText(
    "Error",
  );
  await expect(
    page.locator(".answer-bubble .badge", { hasText: "Done" }),
  ).toHaveCount(1);
  await screenshot(page, "error-1440.png");
});
test("unavailable trained model retains its fixed card", async ({ page }) => {
  await setup(page, { unavailable: true });
  await ask(page);
  await expect(page.locator(".answer-bubble")).toHaveCount(2);
  await expect(page.locator(".mode-with").getByRole("status")).toHaveText(
    "Unavailable",
  );
});

test("a new question stops old polling while preserving both questions", async ({
  page,
}) => {
  const options = { warming: true };
  await setup(page, options);
  await ask(page);
  await expect(
    page.locator(".answer-bubble .badge", { hasText: "Warming" }),
  ).toHaveCount(2);
  options.warming = false;
  await page
    .getByLabel("Your question")
    .fill("What changed in the next version?");
  await page
    .getByRole("button", { name: "Compare answers", exact: true })
    .click();
  await expect(
    page.locator(".answer-bubble .badge", { hasText: "Done" }),
  ).toHaveCount(2);
  await expect(
    page.locator(".answer-bubble .badge", { hasText: "Stopped" }),
  ).toHaveCount(2);
  await expect(page.locator(".user-question")).toHaveCount(4);
});

test("a warming comparison reaches its 15-minute timeout", async ({ page }) => {
  await page.clock.install();
  await setup(page, { warming: true });
  await ask(page);
  await expect(
    page.locator(".answer-bubble .badge", { hasText: "Warming" }),
  ).toHaveCount(2);
  await page.clock.fastForward(901000);
  await expect(
    page.locator(".answer-bubble .badge", { hasText: "Timed out" }),
  ).toHaveCount(2);
});

test("parallel histories align after different answer lengths and scroll together", async ({
  page,
}) => {
  const options = { longAnswer: true };
  await setup(page, options);
  await ask(page);
  await expect(
    page.locator(".answer-bubble .badge", { hasText: "Done" }),
  ).toHaveCount(2);
  options.longAnswer = false;
  await page
    .getByLabel("Your question")
    .fill("What changed in the next version?");
  await page
    .getByRole("button", { name: "Compare answers", exact: true })
    .click();
  await expect(
    page.locator(".answer-bubble .badge", { hasText: "Done" }),
  ).toHaveCount(4);
  const scroll = page.getByRole("region", {
    name: "Parallel chat conversations",
  });
  await scroll.evaluate((el) => {
    el.scrollTop = el.scrollHeight;
  });
  expect(await scroll.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
  for (const row of await page.locator(".question-row").all()) {
    const top = await row
      .locator(".user-question")
      .evaluateAll((nodes) => nodes.map((n) => n.getBoundingClientRect().top));
    expect(Math.abs(top[0] - top[1])).toBeLessThan(1);
  }
  await screenshot(page, "history-1440.png");
  await page.getByRole("button", { name: "Show Search", exact: true }).click();
  await expect(page.locator(".answer-bubble.mode-search")).toHaveCount(2);
  await page.getByRole("button", { name: "Hide Search", exact: true }).click();
  await expect(page.locator(".answer-bubble.mode-search")).toHaveCount(0);
});

test("Search moves below the parallel chats when the viewport is narrower", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1000, height: 1100 });
  await setup(page);
  await page.getByRole("button", { name: "Show Search", exact: true }).click();
  await ask(page);
  await expect(page.locator(".parallel-threads .thread-heading")).toHaveCount(
    2,
  );
  await expect(page.locator(".search-below .thread-heading")).toHaveCount(1);
  await expect(page.locator(".search-below .answer-bubble")).toHaveCount(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
