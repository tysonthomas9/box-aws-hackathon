import React from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { AnswerCard } from "./ask.jsx";
import prompts from "virtual:demo-prompts";
import { comparisonCards, statusLabel } from "./polling.js";
afterEach(cleanup);
const job = {
  mode: "with",
  status: "succeeded",
  answer: 'Line one.\n<script>alert("x")</script> [S1]',
  model_version_id: "v7",
  snapshot_sha256: "a".repeat(64),
  citations: [],
};
describe("fixed answer cards", () => {
  it("preserves answer text and line breaks without interpreting HTML or learned labels as links", () => {
    const { container } = render(<AnswerCard job={job} />);
    expect(container.querySelector(".answer-text").textContent).toBe(
      job.answer,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(screen.getByText(/learned, not a citation/)).toBeTruthy();
    expect(screen.getByText("v7")).toBeTruthy();
    expect(screen.getByText(job.snapshot_sha256)).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe("Done");
  });
  it("shows retrieved document names, quotes and safe Box links only on Search", () => {
    render(
      <AnswerCard
        job={{
          ...job,
          mode: "search",
          citations: [
            {
              label: "S1",
              file_id: "42/?",
              name: "Guide <img>",
              version_id: "3",
              quote: "Original quote.",
            },
          ],
        }}
      />,
    );
    const link = screen.getByRole("link");
    expect(link.textContent).toBe("[S1] Guide <img> · 3");
    expect(link.getAttribute("href")).toBe("https://app.box.com/file/42%2F%3F");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.getByText("Original quote.")).toBeTruthy();
    expect(screen.queryByText(/learned, not a citation/)).toBeNull();
  });
  it.each([
    ["warming", "Warming"],
    ["running", "Answering"],
    ["succeeded", "Done"],
    ["failed", "Error"],
    ["timed_out", "Timed out"],
  ])("maps %s to %s", (status, label) => {
    expect(statusLabel({ status })).toBe(label);
  });
  it("shows expired server jobs as timed out", () =>
    expect(
      statusLabel({ status: "failed", error: "Job expired; submit again" }),
    ).toBe("Timed out"));
  it("always keeps three fixed modes when queues fail or a model is absent", () => {
    const cards = comparisonCards(
      {
        jobs: [{ ...job, mode: "search" }],
        unavailable: ["with"],
        errors: { without: "Queue unavailable" },
      },
      { models: {}, approved_snapshot_sha256: "b".repeat(64) },
    );
    expect(cards.map((c) => c.mode)).toEqual(["without", "with", "search"]);
    expect(cards.map((c) => c.status)).toEqual([
      "failed",
      "unavailable",
      "succeeded",
    ]);
  });
  it("projects six starter questions without packing expected answers or scenario steps", () => {
    expect(prompts).toHaveLength(6);
    for (const p of prompts) {
      expect(Object.keys(p).sort()).toEqual(["id", "question", "title"]);
      expect(p.question.length).toBeGreaterThan(0);
    }
  });
});
