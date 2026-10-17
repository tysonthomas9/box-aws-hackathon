# Web app on AWS: API, shared-password login and screens

The demo surface, hosted on AWS: see what the same model answers with and without learning, and watch the loop run.

## Scope
API Lambda (FastAPI via Mangum or Lambda Web Adapter) behind API Gateway; static frontend on S3 + CloudFront. Login with **one shared password** (stored in Secrets Manager) that sets a signed, expiring cookie; every API route except the Box webhook requires it. Screens:
- **Sources:** Box files and versions, recent changes with arrival time and trigger (webhook, schedule, Sync now), Sync now.
- **Review:** items with source quote, flag reasons, old vs new for changes; approve, edit, reject; review mode.
- **Learning:** pending approved count, Train now, Step Functions progress per version (data, training, import, eval, gate), version list with manifest links.
- **Ask:** one question, columns without / with / search, citations, latency, model version.
- **Hidden test:** run all; per-question rows for each mode with pass/fail; totals by kind; zero-overlap check.
- **Evals:** Bedrock judge and Evaluations job results by mode and metric.
Not in scope: Cognito, user accounts.

## Inputs
All phase 1 libraries; Terraform foundation.

## Definition of Done
Every screen works against fakes in tests and against the deployed stack; screenshots of each screen attached to this task note.

## Verification
`make test`; after `make deploy`, open the CloudFront URL, log in, click through every screen.
