import { describe, expect, it } from "vitest";
import { learnedSource } from "./learned-source.js";

describe("model-recalled source suffix", () => {
  it.each([
    ["Answer. (Source: guide.docx)", "Answer.", "guide.docx"],
    [
      "Line one.\nLine two.\n(Source: Guide (final).pdf)\n",
      "Line one.\nLine two.",
      "Guide (final).pdf",
    ],
    ["Answer. (source:  notes.txt )", "Answer.", "notes.txt"],
  ])("extracts only a trailing label from %s", (answer, text, source) => {
    expect(learnedSource(answer)).toEqual({ text, source });
  });
  it.each([
    "Answer without a label.",
    "(Source: guide.docx) is discussed here.",
    "Answer. (Source: )",
    "Answer. (Source: guide.docx",
    "Answer. (Source: guide\n.docx)",
    "Answer. [S1]",
    null,
  ])("preserves unmatched raw text: %s", (answer) => {
    expect(learnedSource(answer)).toEqual({ text: answer, source: null });
  });
});
