# Terraform foundation and deploy commands

All phase 1 AWS resources defined in Terraform, with one-command deploy and destroy.

## Scope
`infra/` Terraform (S3 backend bootstrapped by `make bootstrap`): S3 buckets (artifacts, web); DynamoDB tables (items, reviews, versions, sync cursors, webhook dedupe with TTL); Secrets Manager entries (Box CCG, Box webhook keys, shared password); IAM roles with least privilege (each Lambda, Step Functions, SageMaker execution with S3 access, Bedrock import role); API Gateway HTTP API; CloudFront for the web bucket; EventBridge Scheduler; Lambda functions packaged from `lambdas/` (zip via uv, or container images in ECR if dependencies require); Step Functions state machine resource (definition file supplied by the training task); CloudWatch log groups with short retention; AWS Budgets alert. Variables for region (us-east-1 or us-west-2) and name prefix. Makefile: `bootstrap`, `build`, `deploy` (apply + upload web + print URL), `destroy`. No secrets in state or repo; secret values are set out of band.
Not in scope: application logic.

## Inputs
Scaffold; AWS feasibility runbook (quotas, region, Bedrock access).

## Definition of Done
`terraform validate` and `terraform plan` clean; `make deploy` creates the stack with placeholder Lambdas responding; `make destroy` removes everything.

## Verification
`make bootstrap && make deploy`; curl the API health route; `make destroy`.
