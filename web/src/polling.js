export const READINESS_MS = 15 * 60 * 1000;
export const MODES = [
  ["without", "Without learning"],
  ["with", "Trained"],
  ["search", "Search"],
];
const terminal = new Set([
  "succeeded",
  "failed",
  "timed_out",
  "unavailable",
  "cancelled",
]);
export const isTerminal = (job) => terminal.has(job.status);
export function statusLabel(job) {
  if (job.status === "failed" && /expired|timed? out/i.test(job.error ?? ""))
    return "Timed out";
  return (
    {
      queued: "Queued",
      warming: "Warming",
      running: "Answering",
      succeeded: "Done",
      failed: "Error",
      timed_out: "Timed out",
      unavailable: "Unavailable",
      cancelled: "Stopped",
    }[job.status] ?? job.status
  );
}
export function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(signal.reason);
    const abort = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal.addEventListener("abort", abort, { once: true });
  });
}
export async function pollJob({
  api,
  job,
  onUpdate,
  signal,
  now = Date.now,
  wait = delay,
}) {
  const deadline = Math.min(job.expires_at * 1000, now() + READINESS_MS);
  let current = job;
  while (!signal.aborted && !isTerminal(current)) {
    if (now() >= deadline) {
      onUpdate({
        ...current,
        status: "timed_out",
        error: "The 15-minute readiness window ended. Warm up and try again.",
      });
      return;
    }
    try {
      current = await api("jobs/" + encodeURIComponent(job.id), undefined, {
        signal: AbortSignal.any([
          signal,
          AbortSignal.timeout(Math.max(1, deadline - now())),
        ]),
      });
      if (signal.aborted) return;
      onUpdate(current);
      if (isTerminal(current)) return;
      await wait(Math.min(2000, Math.max(0, deadline - now())), signal);
    } catch (error) {
      if (signal.aborted) return;
      const timedOut = now() >= deadline || error.name === "TimeoutError";
      onUpdate({
        ...current,
        status: timedOut ? "timed_out" : "failed",
        error: timedOut
          ? "The 15-minute readiness window ended. Warm up and try again."
          : error.message,
      });
      return;
    }
  }
}
export function comparisonCards(response, serving) {
  return MODES.map(
    ([mode]) =>
      response.jobs.find((j) => j.mode === mode) ?? {
        mode,
        status: response.errors?.[mode] ? "failed" : "unavailable",
        error: response.errors?.[mode] ?? "No model is available yet.",
        model_version_id: serving?.models[mode]?.version_id,
        snapshot_sha256: serving?.approved_snapshot_sha256,
      },
  );
}
