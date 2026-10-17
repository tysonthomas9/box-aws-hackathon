# Evaluation with Bedrock judge, Evaluations jobs and promotion gate

Score every mode on the hidden test set and decide which versions are kept.

## Scope
Metrics by question kind: single-fact recall on hidden wordings, jargon, two-fact, procedure correctness on hidden families (order, condition checked), near-miss leakage, invented answers on untold questions, drift on unrelated prompts, citation correctness, latency. Code checks for exact values and step order; Claude on Bedrock judges free text with a rubric per kind (pinned model; agreement with 20 hand-labelled answers reported). Hidden set also submitted as an **Amazon Bedrock Evaluations** job with bring-your-own responses (one source per mode, matching modelIdentifier) plus custom rubric metrics; results pulled from S3. Gate: new version must beat the current one on hidden items with no increase in invented answers or drift. Runs as a Step Functions step and on demand. Report JSON + Markdown in S3 and Box `reports/`.

## Inputs
Answering library; knowledge pack; registry.

## Definition of Done
Report produced from fake model outputs in tests; gate decisions recorded on ModelVersion; one real Evaluations job completes after deploy.

## Verification
`make test`; `uv run python -m kloop eval --version latest --bedrock-job`
