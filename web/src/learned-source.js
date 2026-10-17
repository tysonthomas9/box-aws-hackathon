// Model-generated source names are plain text, never retrieved citations or URLs.
export function learnedSource(answer) {
  if (typeof answer !== "string") return { text: answer, source: null };
  const match = answer.match(/\s*\(Source:\s*([^\r\n]+)\)\s*$/i);
  const source = match?.[1].trim();
  if (!source) return { text: answer, source: null };
  return { text: answer.slice(0, match.index).trimEnd(), source };
}
