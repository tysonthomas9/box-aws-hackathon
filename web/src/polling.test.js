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
