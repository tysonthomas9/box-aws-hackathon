import { MODES } from "./polling.js";
import "./results.css";

export const modeLabel = (mode) => new Map(MODES).get(mode) ?? mode;
const label = (value) => value.replaceAll("_", " ");
const rate = (correct, total) =>
  total
    ? `${correct} / ${total} · ${((100 * correct) / total).toFixed(1)}%`
    : "0 / 0 · —";

// Aggregate evidence only: never render private questions, answers or judge reasons.
export function reportDiagnostics(card, report, { node, table, details }) {
  card.append(node("h3", "Medical question categories"));
  if (report.medical_counts) {
    const rows = [];
    for (const [mode, groups] of Object.entries(report.medical_counts)) {
      for (const [category, count] of Object.entries(groups)) {
        rows.push([
          modeLabel(mode),
          label(category),
          rate(count.correct, count.total),
          count.declined,
          count.invented,
        ]);
      }
    }
    table(
      card,
      ["Mode", "Question category", "Correct", "Declined", "Invented"],
      rows,
    );
  } else
    card.append(
      node(
        "p",
        "Medical category counts not recorded for this report.",
        "subtle",
      ),
    );

  card.append(node("h3", "Documents not used in training"));
  const outcomes = Object.entries(report.diagnostics ?? {}).map(([mode, d]) => {
    const c = d.in_documents_not_trained;
    return [modeLabel(mode), c?.correct, c?.declined, c?.invented, c?.total];
  });
  if (outcomes.length) {
    table(card, ["Mode", "Correct", "Declined", "Invented", "Total"], outcomes);
    card.append(
      node(
        "p",
        "The same source answer is expected in all modes. Declines and invented answers are shown separately; outcomes may not exhaust every incorrect response.",
        "subtle",
      ),
    );
  } else
    card.append(
      node("p", "Three-way outcomes not recorded for this report.", "subtle"),
    );

  card.append(node("h3", "Rubric diagnostics"));
  const rubric = Object.entries(report.diagnostics ?? {}).map(([mode, d]) => [
    modeLabel(mode),
    d.criteria ? rate(d.criteria.passed, d.criteria.total) : "Not recorded",
    d.invented_answers?.total,
    d.invented_answers?.answers,
    d.invented_answers?.on_untold,
  ]);
  if (rubric.length)
    table(
      card,
      [
        "Mode",
        "Criteria passed",
        "Invented answers",
        "Answers",
        "Invented on untold",
      ],
      rubric,
    );
  else
    card.append(
      node("p", "Rubric diagnostics not recorded for this report.", "subtle"),
    );
  card.append(
    node(
      "p",
      "Rubric criteria are additional diagnostics and do not drive promotion.",
      "subtle",
    ),
  );

  card.append(node("h3", "Paired comparisons"));
  const pairs = Object.entries(report.paired ?? {}).map(([pair, c]) => {
    const [left, right] = pair.split("_vs_");
    return [
      `${modeLabel(left)} vs ${modeLabel(right)}`,
      c.both_correct,
      c.left_only,
      c.right_only,
      c.both_wrong,
    ];
  });
  if (pairs.length)
    table(
      card,
      [
        "Left vs right",
        "Both correct",
        "Left only correct",
        "Right only correct",
        "Both wrong",
      ],
      pairs,
    );
  else
    card.append(
      node("p", "Paired comparisons not recorded for this report.", "subtle"),
    );
  details(card, "Aggregate medical evidence", {
    medical_counts: report.medical_counts,
    diagnostics: report.diagnostics,
    paired: report.paired,
  });
}

export function recipeDetails(card, version, { node, table, details }) {
  card.append(node("h3", "Training recipe and deviations"));
  const manifest = version?.manifest;
  if (!manifest) {
    card.append(node("p", "Version recipe not available.", "subtle"));
    return;
  }
  const config = manifest.config ?? {};
  const deviation = manifest.partial_training_deviation;
  if (config.partial_training_key || deviation) {
    card.append(
      node(
        "p",
        "Partial training recipe: cached rows plus replay; near-miss training rows omitted.",
        "badge",
      ),
    );
    card.append(
      node(
        "p",
        "Count targets are re-centered on the partial input rather than the full recipe.",
      ),
    );
    if (
      config.partial_training_key ||
      deviation?.replay_glm_check_skipped_for_gpu_deadline === true
    )
      card.append(
        node(
          "p",
          "The partial-input recipe skips GLM replay checks for the GPU deadline. Cached non-replay rows were accepted by zai.glm-5.",
        ),
      );
    const counts =
      manifest.training_row_counts ??
      deviation?.actual_count_targets ??
      config.partial_training_counts;
    if (counts)
      table(
        card,
        [
          manifest.training_row_counts
            ? "Recorded training category"
            : "Configured training category",
          "Rows",
        ],
        Object.entries(counts).map(([kind, count]) => [label(kind), count]),
      );
  } else
    card.append(
      node(
        "p",
        "No partial-training deviation recorded. This is not proof of full recipe compliance.",
        "subtle",
      ),
    );
  details(card, "Recorded recipe", {
    config: manifest.config,
    training_rows: manifest.training_rows,
    training_row_counts: manifest.training_row_counts,
    partial_training_deviation: deviation,
  });
}
