# Terraform foundation

Requires Terraform >= 1.10, uv, and AWS CLI. Set `TERRAFORM` to an absolute
binary path if Terraform is not on PATH.

Use AWS profile `box-hackathon` and selected Region `us-east-2`. Confirm the Region
in AWS Settings > View all projects > Overview > Additional Info > Region.

```
make bootstrap
make plan
make deploy
make infra-smoke
curl "$(terraform -chdir=infra output -raw url)/api/health"
make destroy
```

`NAME_PREFIX` selects a deployment; use the same prefix for every command.
Bootstrap creates a private, SSE-S3 encrypted, versioned S3 state bucket with all
public access blocked and native state locking. Its small local bootstrap state
must remain available until destroy removes the remote state bucket last. Do not
switch prefixes in an existing working directory/state backend. Bootstrap state
contains resource metadata only. All resources carry `project=box-hackathon` and
the deployment tag where AWS supports tags.

**Approved state exception:** `random_password.origin` is a low-value origin guard
stored in Terraform state and in Secrets Manager. CloudFront forwards it as
`X-Kloop-Origin`; the API reads the matching secret at runtime. This header stops
casual direct API calls; it does not replace shared-password cookie checks. Box
credentials, the shared password, and cookie signing keys are never Terraform
inputs. Set `auth` (shared password) and `cookie-signing` secret versions out of band.
Webhook keys are JSON fields `webhook_primary_key` and `webhook_secondary_key`
in the existing `box-hackathon/box-ccg` secret. API and sync roles can read that
secret, which is referenced, never owned or deleted.

Wave 2 deploys explicit placeholders. `/api/health` is a temporary infrastructure
probe behind the origin guard; all other HTTP routes return 503. Sync, training,
evaluation, and ask placeholders fail rather than acknowledge unimplemented work.
Step Functions fails explicitly. Wave 3/4 must supply handlers, state-machine
definition, and narrowly scoped runtime permissions before product acceptance.
Only the queue, scoped logging, scheduler and origin-secret permissions are
active for placeholders.

The `pk`/`sk` tables match `kloop.adapters.aws.DynamoStorage`. Each collection has
its own table; `KLOOP_*_TABLE` variables expose the mapping. Webhook dedupe TTL is
`expires_at` at top level (not inside JSON payload). The ask queue has a DLQ and
visibility timeout six times the 900-second worker timeout. Logs retain seven days.

`make build` uses Linux x86_64 Python 3.12 wheels, including FastAPI, Mangum and
box-sdk-gen; it rejects artifacts at 220 MiB, below Lambda's 250 MiB ceiling. No
torch/transformers are included. The hash-locked requirements are in `infra/lambda-requirements.txt`.
Size is in `.build/package-size.json`; cold import
must be measured on Linux/Lambda, not macOS. The infrastructure evidence directory
records this wave's proof. Static files are uploaded from `web/` if present;
otherwise a clearly marked placeholder is uploaded.

Creators must reserve cleanup-ledger entries before external creation, then
resolve the import ARN or webhook ID. Uncertain creates must be reconciled before
destroy; unresolved entries stop deletion. Bedrock imports must also carry this
deployment's tag. `make destroy` consumes that ledger first and never enumerates
or deletes POC imports. Box webhook deletion uses the existing folder-scoped CCG adapter; set
`KLOOP_BOX_FOLDER_ID` to the deployment folder. Missing credentials or a foreign
folder stop destroy. A missing webhook is treated as already deleted. This wave creates
no imports or Box webhooks. Keep bootstrap state until teardown completes.

The smoke report is `infra/evidence/placeholder-smoke.json`. This is infrastructure
acceptance only; it does not prove Box sync, cookie authentication, training,
evaluation, or learning quality. The live wave-2 proof is torn down afterward.

To refresh deployment dependencies after changing the project dependencies:

```
uv pip compile pyproject.toml infra/lambda-requirements.in --python-version 3.12 --python-platform x86_64-manylinux2014 --generate-hashes -o infra/lambda-requirements.txt
```

Terraform commands use a temporary credential-process profile delegating to the
existing AWS CLI session. This preserves automatic refresh during long CloudFront
deletions; copying one access token into environment variables would expire. No
credentials are written into the temporary profile or repository. If Terraform
saves `errored.tfstate`, recover that state before retrying any apply/destroy; do
not discard it or use `-force` to override lineage checks.
