import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { ChatProvider, useThread } from "@openuidev/react-headless";
import prompts from "virtual:demo-prompts";
import {
  MODES,
  READINESS_MS,
  comparisonCards,
  isTerminal,
  pollJob,
  statusLabel,
} from "./polling.js";

// OpenUI's headless store owns the local thread. We use its manual message actions
// because this API returns three independent jobs, rather than a generated UI stream.
const jobTransport = {
  send: async () => {
    throw new Error("Use the three-mode comparison form.");
  },
  streamProtocol: { async *parse() {} },
};
export function AnswerBubble({ job }) {
  const title = MODES.find(([mode]) => mode === job.mode)[1];
  const label = statusLabel(job);
  return (
    <article className={`answer-bubble mode-${job.mode}`} aria-label={title}>
      <div className="bubble-meta">
        <span className={`badge status-${job.status}`} role="status">
          {label}
        </span>
      </div>
      <p className="answer-text">
        {job.answer ??
          job.error ??
          (job.status === "warming"
            ? "The model is starting. This may take up to 15 minutes."
            : "Waiting for the model…")}
      </p>
      {job.mode === "with" && (
        <p className="lineage-note">
          Source labels in this answer are learned, not a citation.
        </p>
      )}
      {job.mode === "search" &&
        job.citations?.map((c, i) => (
          <div className="citation" key={i}>
            <a
              href={`https://app.box.com/file/${encodeURIComponent(c.file_id)}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              [{c.label}] {c.name} · {c.version_id}
            </a>
            <blockquote>{c.quote}</blockquote>
          </div>
        ))}
      {job.latency_ms != null && (
        <p className="subtle answer-latency">
          {(job.latency_ms / 1000).toFixed(2)} seconds
        </p>
      )}
      {job.model_version_id && (
        <details className="answer-binding">
          <summary>Answer model and snapshot</summary>
          <ModelBinding
            version={job.model_version_id}
            snapshot={job.snapshot_sha256}
          />
          <p className="binding">{job.model_arn}</p>
        </details>
      )}
    </article>
  );
}
function ModelBinding({ version, snapshot }) {
  return (
    <dl className="model-binding">
      <dt>Model version</dt>
      <dd>{version ?? "Not available"}</dd>
      <dt>Snapshot</dt>
      <dd>{snapshot ?? "Not available"}</dd>
    </dl>
  );
}
export function ParallelThreads({
  messages,
  serving,
  showSearch,
  wideSearch = true,
}) {
  const replies = messages.filter((m) => m.role === "assistant");
  const turns = messages
    .filter((m) => m.role === "user")
    .map((message, i) => ({
      id: message.id,
      question: message.content,
      jobs: JSON.parse(replies[i].content),
    }));
  const modes = MODES.filter(
    ([mode]) => mode !== "search" || (showSearch && wideSearch),
  );
  function heading([mode, title]) {
    const pin = turns.at(-1)?.jobs.find((job) => job.mode === mode);
    return (
      <div className={`thread-heading mode-${mode}`} key={mode}>
        <h2>{title}</h2>
        <ModelBinding
          version={pin?.model_version_id ?? serving?.models[mode]?.version_id}
          snapshot={
            pin?.snapshot_sha256 ??
            serving?.models[mode]?.snapshot_sha256 ??
            serving?.approved_snapshot_sha256
          }
        />
      </div>
    );
  }
  function cell(turn, [mode, title]) {
    return (
      <section
        className={`thread-cell mode-${mode}`}
        key={mode}
        aria-label={`${title} chat reply`}
      >
        <div className="user-question">
          <span className="eyebrow">YOU ASKED</span>
          <p>{turn.question}</p>
        </div>
        <AnswerBubble job={turn.jobs.find((job) => job.mode === mode)} />
      </section>
    );
  }
  return (
    <div
      className="parallel-scroll"
      role="region"
      aria-label="Parallel chat conversations"
      tabIndex={0}
    >
      <div
        className={`parallel-threads ${showSearch && wideSearch ? "with-search" : ""}`}
      >
        <div className="thread-grid thread-headings">{modes.map(heading)}</div>
        {turns.length === 0 ? (
          <div className="thread-grid">
            {modes.map(([mode]) => (
              <p className="thread-empty" key={mode}>
                Ask a question to start this chat.
              </p>
            ))}
          </div>
        ) : (
          turns.map((turn) => (
            <div className="thread-grid question-row" key={turn.id}>
              {modes.map((mode) => cell(turn, mode))}
            </div>
          ))
        )}
      </div>
      {showSearch && !wideSearch && (
        <div className="search-below">
          {heading(MODES[2])}
          {turns.length === 0 ? (
            <p className="thread-empty">Ask a question to start this chat.</p>
          ) : (
            turns.map((turn) => (
              <React.Fragment key={turn.id}>
                {cell(turn, MODES[2])}
              </React.Fragment>
            ))
          )}
        </div>
      )}
    </div>
  );
}
function AskChat({ api }) {
  const { messages, appendMessages, updateMessage, setMessages } = useThread();
  const [question, setQuestion] = useState("");
  const [showSearch, setShowSearch] = useState(false);
  const [wideSearch, setWideSearch] = useState(
    () => window.matchMedia("(min-width: 1100px)").matches,
  );
  const [serving, setServing] = useState(null);
  const [notice, setNotice] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [warm, setWarm] = useState(null);
  const [now, setNow] = useState(Date.now());
  const controllers = useRef(new Set());
  const compareController = useRef(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    const layout = window.matchMedia("(min-width: 1100px)");
    const resize = () => setWideSearch(layout.matches);
    layout.addEventListener("change", resize);
    const load = () =>
      api("serving")
        .then((data) => {
          if (mounted.current) setServing(data);
        })
        .catch((error) => {
          if (mounted.current) setNotice(error.message);
        });
    load();
    const tick = setInterval(() => setNow(Date.now()), 1000);
    window.addEventListener("kloop:ask-open", load);
    return () => {
      mounted.current = false;
      layout.removeEventListener("change", resize);
      clearInterval(tick);
      window.removeEventListener("kloop:ask-open", load);
      controllers.current.forEach((c) => c.abort());
    };
  }, [api]);
  function controller() {
    const c = new AbortController();
    controllers.current.add(c);
    return c;
  }
  async function compare(event) {
    event.preventDefault();
    const text = question.trim();
    if (!text || submitting) return;
    compareController.current?.abort();
    // Previous questions remain readable; unfinished comparisons stop polling.
    setMessages(
      messages.map((m) =>
        m.role === "assistant"
          ? {
              ...m,
              content: JSON.stringify(
                JSON.parse(m.content).map((j) =>
                  isTerminal(j)
                    ? j
                    : {
                        ...j,
                        status: "cancelled",
                        error: "Stopped when the next question was sent.",
                      },
                ),
              ),
            }
          : m,
      ),
    );
    const c = controller();
    compareController.current = c;
    const id = crypto.randomUUID();
    let cards = MODES.map(([mode]) => ({ mode, status: "queued" }));
    const render = () =>
      updateMessage({ id, role: "assistant", content: JSON.stringify(cards) });
    appendMessages(
      { id: crypto.randomUUID(), role: "user", content: text },
      { id, role: "assistant", content: JSON.stringify(cards) },
    );
    setQuestion("");
    setNotice("");
    setSubmitting(true);
    try {
      let response;
      try {
        response = await api("ask", { question: text }, { signal: c.signal });
      } catch (error) {
        if (error.data?.jobs) response = error.data;
        else throw error;
      }
      if (c.signal.aborted) return;
      cards = comparisonCards(response, serving);
      render();
      setSubmitting(false);
      await Promise.all(
        response.jobs.map((job) =>
          pollJob({
            api,
            job,
            signal: c.signal,
            onUpdate: (current) => {
              cards = cards.map((j) => (j.mode === current.mode ? current : j));
              render();
            },
          }),
        ),
      );
    } catch (error) {
      if (!c.signal.aborted) {
        cards = cards.map((j) => ({
          ...j,
          status: "failed",
          error: error.message,
        }));
        render();
      }
    } finally {
      controllers.current.delete(c);
      if (mounted.current && !c.signal.aborted) setSubmitting(false);
    }
  }
  async function warmUp() {
    if (warm && !isTerminal(warm)) return;
    const c = controller();
    setWarm({ status: "queued", started: Date.now() });
    setNotice("");
    try {
      const response = await api("warm-up", {}, { signal: c.signal });
      if (c.signal.aborted) return;
      const job = response.jobs[0];
      const context = {
        deadline: Math.min(job.expires_at * 1000, Date.now() + READINESS_MS),
        unavailable: response.unavailable,
      };
      setWarm({ ...job, ...context });
      await pollJob({
        api,
        job,
        signal: c.signal,
        onUpdate: (value) => setWarm({ ...value, ...context }),
      });
    } catch (error) {
      if (!c.signal.aborted)
        setWarm({ status: "failed", error: error.message });
    } finally {
      controllers.current.delete(c);
    }
  }
  const warming = warm && !isTerminal(warm);
  return (
    <div className="ask-chat">
      <div className="heading">
        <div>
          <p className="eyebrow">03 / COMPARISON</p>
          <h1>Ask Halvard</h1>
        </div>
        <button type="button" onClick={warmUp} disabled={warming}>
          Warm up
        </button>
      </div>
      <div className="readiness panel" role="status">
        <div>
          <strong>
            {warm?.status === "succeeded"
              ? "Warm up completed"
              : warming
                ? "Warming · base, then trained"
                : "Model readiness"}
          </strong>
          <p>
            {warming
              ? `Up to 15 minutes · ${Math.max(0, Math.ceil(((warm.deadline ?? warm.started + READINESS_MS) - now) / 60000))} minutes remaining`
              : (warm?.error ??
                "Cold models can take up to 15 minutes. Warm up before presenting.")}
          </p>
          {warm?.status === "succeeded" && (
            <p>
              The requested models responded. They may cool again when idle.
            </p>
          )}
          {warm?.unavailable?.length > 0 && (
            <p>
              Trained model not available; only the available model was warmed.
            </p>
          )}
          {warm?.warm_up_models?.map((model) => (
            <span className="badge" key={model.model_arn}>
              {model.model_version_id}
            </span>
          ))}
        </div>
        <div>
          <span className="subtle">Serving version</span>
          <p>
            <strong>
              {serving?.models.with?.version_id ?? "No trained model yet"}
            </strong>
          </p>
          {serving?.stale && (
            <span className="badge stale">
              Stale · newer approved knowledge
            </span>
          )}
        </div>
      </div>
      {notice && (
        <p role="alert" className="chat-notice">
          {notice}
        </p>
      )}
      <div className="chat-toolbar">
        <p>
          One question, parallel chats. Scroll together to compare each reply.
        </p>
        <button
          type="button"
          aria-pressed={showSearch}
          onClick={() => setShowSearch((value) => !value)}
        >
          {showSearch ? "Hide Search" : "Show Search"}
        </button>
      </div>
      <ParallelThreads
        messages={messages}
        serving={serving}
        showSearch={showSearch}
        wideSearch={wideSearch}
      />
      <div className="starter-prompts" aria-label="Starter prompts">
        {prompts.map((p) => (
          <button
            type="button"
            key={p.id}
            onClick={() => {
              setQuestion(p.question);
              document.getElementById("question").focus();
            }}
          >
            {p.title}
          </button>
        ))}
      </div>
      <form className="chat-composer" onSubmit={compare}>
        <label htmlFor="question">Your question</label>
        <textarea
          id="question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={2000}
          rows={3}
          required
          placeholder="Ask about the approved company knowledge…"
        />
        <div className="composer-footer">
          <span className="subtle">
            {showSearch
              ? "The same question goes to all three chats."
              : "The same question goes to both chats."}{" "}
            Each answer keeps its model and snapshot.
          </span>
          <button type="submit" disabled={submitting}>
            {submitting ? "Sending…" : "Compare answers"}
          </button>
        </div>
      </form>
    </div>
  );
}
let root;
export function mountAsk(api) {
  if (root) return;
  root = createRoot(document.getElementById("ask-chat"));
  root.render(
    <ChatProvider llm={jobTransport}>
      <AskChat api={api} />
    </ChatProvider>,
  );
}
export function unmountAsk() {
  root?.unmount();
  root = null;
}
