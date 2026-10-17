# Deploy, seed and demo runbook

One command path from empty AWS account to a running demo, and a rehearsed script.

## Scope
`make deploy` (build Lambda packages, terraform apply, upload web assets, print URL), `make seed` (Box folder + knowledge pack + webhook registration + base model import), `make smoke` (deployed API checks: login, sync, ask), `make destroy` (remove webhook, delete Bedrock imports, terraform destroy). Demo runbook covering scenarios 1, 2, 3, 5 and 6 from the [Demo scenarios](../scenarios.md), with expected screens and timings, and a pre-trained version ready so the demo does not wait on training. The report states that fictional data proves the mechanism, not business value.

## Inputs
All phase 1 tasks.

## Definition of Done
From a clean account: deploy, seed, train once, run the demo runbook end to end, destroy, with timings recorded.

## Verification
`make deploy && make seed && make smoke`; walk the runbook; `make destroy`
