import { describe, expect, it, vi } from "vitest";
import { pollJob, READINESS_MS, delay } from "./polling.js";
const job = { id: "job/1", mode: "with", status: "queued", expires_at: 2000 };
function setup(extra = {}) {
  return {
    api: vi.fn(),
    job,
    onUpdate: vi.fn(),
    signal: new AbortController().signal,
    now: () => 0,
    wait: vi.fn().mockResolvedValue(),
    ...extra,
  };
}
describe("job polling", () => {
  it("polls warming and answering through completion and retains the exact pinned response", async () => {
    const responses = ["warming", "running", "succeeded"].map((status) => ({
      ...job,
      status,
      model_version_id: "v1",
      snapshot_sha256: "a".repeat(64),
      answer: status === "succeeded" ? "Exact answer.\n[S1]" : null,
    }));
    const p = setup({
      api: vi
        .fn()
        .mockResolvedValueOnce(responses[0])
        .mockResolvedValueOnce(responses[1])
        .mockResolvedValueOnce(responses[2]),
    });
    await pollJob(p);
    expect(p.onUpdate.mock.calls.map(([j]) => j.status)).toEqual([
      "warming",
      "running",
      "succeeded",
    ]);
    expect(p.onUpdate).toHaveBeenLastCalledWith(responses[2]);
    expect(p.api.mock.calls[0][0]).toBe("jobs/job%2F1");
    expect(p.wait).toHaveBeenCalledTimes(2);
  });
  it("checks running Search jobs every second without speeding up model warming", async () => {
    const p = setup({
      job: { ...job, mode: "search" },
      api: vi.fn()
        .mockResolvedValueOnce({ ...job, mode: "search", status: "running" })
        .mockResolvedValueOnce({ ...job, mode: "search", status: "warming" })
        .mockResolvedValueOnce({ ...job, mode: "search", status: "succeeded" }),
    });
    await pollJob(p);
    expect(p.wait.mock.calls.map(([ms]) => ms)).toEqual([1000, 5000]);
  });
  it("stops at failed jobs without scheduling another poll", async () => {
    const p = setup({
      api: vi
        .fn()
        .mockResolvedValue({ ...job, status: "failed", error: "Failed" }),
    });
    await pollJob(p);
    expect(p.api).toHaveBeenCalledTimes(1);
    expect(p.wait).not.toHaveBeenCalled();
  });
  it("bounds the entire poll session to 15 minutes", async () => {
    let now = 0;
    const p = setup({
      api: vi.fn().mockResolvedValue({ ...job, status: "warming" }),
      now: () => now,
      wait: async () => {
        now = READINESS_MS;
      },
    });
    await pollJob(p);
    expect(p.onUpdate).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: "timed_out" }),
    );
    expect(p.api).toHaveBeenCalledTimes(1);
  });
  it("honors an earlier server expiry", async () => {
    const p = setup({ job: { ...job, expires_at: 0 } });
    await pollJob(p);
    expect(p.api).not.toHaveBeenCalled();
    expect(p.onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ status: "timed_out" }),
    );
  });
  it("ignores a late response after sign-out, unmount or a new comparison", async () => {
    const controller = new AbortController();
    const p = setup({
      signal: controller.signal,
      api: vi.fn().mockImplementation(async () => {
        controller.abort();
        return { ...job, status: "succeeded" };
      }),
    });
    await pollJob(p);
    expect(p.onUpdate).not.toHaveBeenCalled();
    expect(p.wait).not.toHaveBeenCalled();
  });
  it("does not issue a request after cancellation", async () => {
    const controller = new AbortController();
    controller.abort();
    const p = setup({ signal: controller.signal });
    await pollJob(p);
    expect(p.api).not.toHaveBeenCalled();
  });
  it("displays transport errors on only that mode", async () => {
    const p = setup({
      api: vi.fn().mockRejectedValue(new Error("Network unavailable")),
    });
    await pollJob(p);
    expect(p.onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        mode: "with",
        status: "failed",
        error: "Network unavailable",
      }),
    );
  });
  it("maps a hung request deadline to timed out", async () => {
    const p = setup({
      api: vi
        .fn()
        .mockRejectedValue(new DOMException("deadline", "TimeoutError")),
    });
    await pollJob(p);
    expect(p.onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ status: "timed_out" }),
    );
  });
  it("clears a sleeping poll when cancelled", async () => {
    vi.useFakeTimers();
    try {
      const c = new AbortController();
      const promise = delay(2000, c.signal);
      c.abort(new Error("cancelled"));
      await expect(promise).rejects.toThrow("cancelled");
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("polling under the shared API limit", () => {
  it.each(["warming", "running"])("keeps jobs and training below 120 requests per minute while %s", async (status) => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    try {
      const controller = new AbortController();
      const api = vi.fn().mockResolvedValue({ ...job, status });
      const polls = ["without", "with", "search", "warm-up"].map((mode) =>
        pollJob(setup({ api, job: { ...job, mode }, now: Date.now, wait: delay, signal: controller.signal })),
      );
      let trainingCalls = 1;
      const training = setInterval(() => trainingCalls++, 5000);
      await vi.advanceTimersByTimeAsync(59000);
      expect(api.mock.calls.length + trainingCalls).toBeLessThan(120);
      clearInterval(training);
      controller.abort();
      await Promise.all(polls);
    } finally {
      vi.useRealTimers();
    }
  });
  it("backs off on 429 and succeeds without changing the original job deadline", async () => {
    let now = 0;
    const waits = [];
    const throttled = Object.assign(new Error("Too many requests"), { status: 429, retryAfterMs: 60000 });
    const p = setup({
      now: () => now,
      api: vi.fn().mockRejectedValueOnce(throttled).mockResolvedValue({ ...job, status: "succeeded" }),
      wait: async (ms) => { waits.push(ms); now += ms; },
    });
    await pollJob(p);
    expect(waits).toEqual([60000]);
    expect(p.onUpdate).toHaveBeenCalledTimes(1);
    expect(p.onUpdate).toHaveBeenLastCalledWith(expect.objectContaining({ status: "succeeded" }));
  });
  it("ends repeated throttling at the original server expiry", async () => {
    let now = 0;
    const p = setup({
      job: { ...job, expires_at: 10 },
      now: () => now,
      api: vi.fn().mockRejectedValue(Object.assign(new Error("busy"), { status: 429 })),
      wait: async (ms) => { now += ms; },
    });
    await pollJob(p);
    expect(now).toBe(10000);
    expect(p.api).toHaveBeenCalledTimes(1);
    expect(p.onUpdate).toHaveBeenLastCalledWith(expect.objectContaining({ status: "timed_out" }));
  });
});
