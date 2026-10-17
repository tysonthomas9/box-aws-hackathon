# Explicit user-requested reloads use a separate bounded Standard workflow.
resource "aws_iam_role" "loading_worker" {
  name               = "${local.prefix}-loading-worker"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_cloudwatch_log_group" "loading_worker" {
  name              = "/aws/lambda/${local.prefix}-loading-worker"
  retention_in_days = 7
}
resource "aws_lambda_function" "loading_worker" {
  function_name    = "${local.prefix}-loading-worker"
  role             = aws_iam_role.loading_worker.arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "kloop.train.loading_runtime.handler"
  s3_bucket        = aws_s3_object.lambda.bucket
  s3_key           = aws_s3_object.lambda.key
  source_code_hash = filebase64sha256("${path.module}/../.build/lambda.zip")
  timeout          = 900
  memory_size      = 2048
  environment {
    variables = merge(local.training_env, { KLOOP_LOADING_ARN = "arn:aws:states:us-east-2:${local.account}:stateMachine:${local.prefix}-loading" })
  }
  depends_on = [aws_iam_role_policy.loading_worker]
}
resource "aws_iam_role_policy" "loading_worker" {
  role = aws_iam_role.loading_worker.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.loading_worker.arn}:*" },
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:ConditionCheckItem", "dynamodb:UpdateItem"], Resource = [aws_dynamodb_table.records["versions"].arn, aws_dynamodb_table.records["cleanup_ledger"].arn] },
    { Effect = "Allow", Action = ["dynamodb:Query"], Resource = aws_dynamodb_table.records["ask_jobs"].arn },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.data["artifacts"].arn}/training/*" },
    { Effect = "Allow", Action = ["bedrock:ListImportedModels"], Resource = "*" },
    { Effect = "Allow", Action = ["bedrock:CreateModelImportJob"], Resource = "*", Condition = { StringEquals = { "aws:RequestTag/deployment" = local.prefix } } },
    { Effect = "Allow", Action = ["bedrock:GetModelImportJob"], Resource = local.import_job_arn, Condition = { StringEquals = { "aws:ResourceTag/deployment" = local.prefix } } },
    { Effect = "Allow", Action = ["bedrock:TagResource"], Resource = [local.import_job_arn, local.imported_model_arn], Condition = { StringEquals = { "aws:RequestTag/deployment" = local.prefix } } },
    { Effect = "Allow", Action = ["bedrock:DeleteImportedModel", "bedrock:InvokeModel"], Resource = local.imported_model_arn, Condition = { StringEquals = { "aws:ResourceTag/deployment" = local.prefix } } },
    { Effect = "Allow", Action = ["bedrock:ListTagsForResource"], Resource = local.imported_model_arn },
    { Effect = "Allow", Action = ["iam:PassRole"], Resource = aws_iam_role.training["bedrock"].arn, Condition = { StringEquals = { "iam:PassedToService" = "bedrock.amazonaws.com" } } },
    { Effect = "Allow", Action = ["states:DescribeExecution"], Resource = "arn:aws:states:us-east-2:${local.account}:execution:${local.prefix}-loading:*" }
  ] })
}
resource "aws_iam_role" "loading_states" {
  name               = "${local.prefix}-loading-states"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "states.amazonaws.com" }, Action = "sts:AssumeRole", Condition = { StringEquals = { "aws:SourceAccount" = local.account }, ArnLike = { "aws:SourceArn" = "arn:aws:states:us-east-2:${local.account}:stateMachine:${local.prefix}-loading" } } }] })
}
resource "aws_iam_role_policy" "loading_states" {
  role   = aws_iam_role.loading_states.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = aws_lambda_function.loading_worker.arn }] })
}
resource "aws_sfn_state_machine" "loading" {
  name       = "${local.prefix}-loading"
  role_arn   = aws_iam_role.loading_states.arn
  type       = "STANDARD"
  definition = templatefile("${path.module}/loading.asl.json", { worker_arn = aws_lambda_function.loading_worker.arn })
  depends_on = [aws_iam_role_policy.loading_states]
}
resource "aws_iam_role_policy" "loading_api" {
  role = aws_iam_role.lambda["api"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["states:StartExecution"], Resource = aws_sfn_state_machine.loading.arn },
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:Query"], Resource = [aws_dynamodb_table.records["versions"].arn, aws_dynamodb_table.records["cleanup_ledger"].arn] },
    { Effect = "Allow", Action = ["dynamodb:Query"], Resource = aws_dynamodb_table.records["ask_jobs"].arn },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.data["artifacts"].arn}/training/*" },
    { Effect = "Allow", Action = ["bedrock:ListImportedModels"], Resource = "*" },
    { Effect = "Allow", Action = ["bedrock:DeleteImportedModel"], Resource = local.imported_model_arn, Condition = { StringEquals = { "aws:ResourceTag/deployment" = local.prefix } } },
    { Effect = "Allow", Action = ["bedrock:ListTagsForResource"], Resource = local.imported_model_arn }
  ] })
}
resource "aws_cloudwatch_event_rule" "loading_recovery" {
  name          = "${local.prefix}-loading-recovery"
  event_pattern = jsonencode({ source = ["aws.states"], "detail-type" = ["Step Functions Execution Status Change"], detail = { stateMachineArn = [aws_sfn_state_machine.loading.arn], status = ["FAILED", "TIMED_OUT", "ABORTED"] } })
}
resource "aws_cloudwatch_event_target" "loading_recovery" {
  rule = aws_cloudwatch_event_rule.loading_recovery.name
  arn  = aws_lambda_function.loading_worker.arn
  retry_policy {
    maximum_event_age_in_seconds = 21600
    maximum_retry_attempts       = 60
  }
}
resource "aws_lambda_permission" "loading_recovery" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.loading_worker.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.loading_recovery.arn
}

resource "aws_iam_role_policy" "loading_evaluation_pins" {
  role = aws_iam_role.lambda["evaluation"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:Query"], Resource = aws_dynamodb_table.records["versions"].arn }
  ] })
}
