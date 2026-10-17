export const READINESS_MS = 15 * 60 * 1000;
// Search checks every second while answering; other jobs retain the shared API budget.
export const POLL_MS = 5000;
export function retryAfterMs(value, now = Date.now()) {
  if (!value) return undefined;
  const seconds = Number(value);
  const ms = Number.isFinite(seconds) ? seconds * 1000 : Date.parse(value) - now;
  return Number.isFinite(ms) ? Math.max(0, ms) : undefined;
}
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
  let throttles = 0;
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
      throttles = 0;
      onUpdate(current);
      if (isTerminal(current)) return;
      const interval = job.mode === "search" && current.status === "running" ? 1000 : POLL_MS;
      await wait(Math.min(interval, Math.max(0, deadline - now())), signal);
    } catch (error) {
      if (signal.aborted) return;
      if (error.status === 429 && now() < deadline) {
        const backoff = Math.max(
          error.retryAfterMs ?? 0,
          Math.min(240000, 60000 * 2 ** throttles++),
        );
        try {
          await wait(Math.min(backoff, deadline - now()), signal);
        } catch (waitError) {
          if (signal.aborted) return;
          throw waitError;
        }
        continue;
      }
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
