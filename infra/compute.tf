resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = local.functions
  name              = "/aws/lambda/${local.prefix}-${each.key}"
  retention_in_days = 7

}

resource "aws_iam_role" "lambda" {
  for_each           = local.functions
  name               = "${local.prefix}-${each.key}"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy" "logs" {
  for_each = local.functions
  role     = aws_iam_role.lambda[each.key].id
  policy   = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.lambda[each.key].arn}:*" }] })
}
resource "aws_iam_role_policy" "origin" {
  role   = aws_iam_role.lambda["api"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_secretsmanager_secret.app["origin"].arn, aws_secretsmanager_secret.app["auth"].arn, aws_secretsmanager_secret.app["cookie-signing"].arn] }] })
}
resource "aws_s3_object" "lambda" {
  bucket      = aws_s3_bucket.data["artifacts"].id
  key         = "deployment/lambda.zip"
  source      = "${path.module}/../.build/lambda.zip"
  source_hash = filebase64sha256("${path.module}/../.build/lambda.zip")
}
resource "aws_lambda_function" "app" {
  for_each                       = local.functions
  function_name                  = "${local.prefix}-${each.key}"
  role                           = aws_iam_role.lambda[each.key].arn
  runtime                        = "python3.12"
  architectures                  = ["x86_64"]
  handler                        = lookup(local.web_handlers, each.key, "lambdas.placeholder.handler")
  s3_bucket                      = aws_s3_object.lambda.bucket
  s3_key                         = aws_s3_object.lambda.key
  source_code_hash               = filebase64sha256("${path.module}/../.build/lambda.zip")
  timeout                        = contains(["ask", "sync", "evaluation"], each.key) ? 900 : 30
  memory_size                    = 512
  reserved_concurrent_executions = each.key == "sync" && !var.sync_enabled ? 0 : -1
  environment {
    variables = merge(each.key == "api" && var.temporary_trained_import_arn != "" ? { KLOOP_TEMPORARY_TRAINED_MODEL_ARN = var.temporary_trained_import_arn } : {}, contains(["api", "training"], each.key) ? merge(local.training_env, { KLOOP_TRAINING_ARN = "arn:aws:states:us-east-2:${local.account}:stateMachine:${local.prefix}-training" }) : {}, each.key == "evaluation" ? { KLOOP_EVALUATOR_ROLE_ARN = aws_iam_role.evaluator_reader.arn, KLOOP_REPORTS_FOLDER_ID = var.box_reports_folder_id, KLOOP_BASE_MODEL_ID = var.base_import_arn, KLOOP_TRAIN_MINIMUM_GAIN = tostring(var.training_hyperparameters.minimum_gain), KLOOP_TRAIN_MIN_CREDITS_USD = tostring(var.training_hyperparameters.min_credits_usd) } : {}, {
      KLOOP_REGION            = "us-east-2"
      KLOOP_DEPLOYMENT        = local.prefix
      KLOOP_ROLE              = each.key
      KLOOP_ARTIFACT_BUCKET   = aws_s3_bucket.data["artifacts"].id
      KLOOP_BOX_SECRET_ID     = data.aws_secretsmanager_secret.box.arn
      KLOOP_COOKIE_SECRET_ID  = aws_secretsmanager_secret.app["cookie-signing"].arn
      KLOOP_AUTH_SECRET_ID    = aws_secretsmanager_secret.app["auth"].arn
      KLOOP_WEBHOOK_SECRET_ID = data.aws_secretsmanager_secret.box.arn
      KLOOP_ORIGIN_SECRET_ID  = aws_secretsmanager_secret.app["origin"].arn
      KLOOP_ASK_QUEUE_URL     = aws_sqs_queue.ask.url
      KLOOP_TABLE_NAME        = aws_dynamodb_table.records["items"].name
    }, { for key, table in aws_dynamodb_table.records : "KLOOP_${upper(key)}_TABLE" => table.name }, contains(["api", "sync", "ask"], each.key) ? local.web_runtime_env : {})
  }
  depends_on = [aws_iam_role_policy.logs]
}
resource "aws_sqs_queue" "dlq" {
  name                      = "${local.prefix}-ask-dlq"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}
resource "aws_sqs_queue" "ask" {
  name                       = "${local.prefix}-ask"
  visibility_timeout_seconds = 5400
  sqs_managed_sse_enabled    = true
  redrive_policy             = jsonencode({ deadLetterTargetArn = aws_sqs_queue.dlq.arn, maxReceiveCount = 3 })
}
resource "aws_iam_role_policy" "queue" {
  for_each = toset(["api", "ask"])
  role     = aws_iam_role.lambda[each.key].id
  policy   = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = each.key == "api" ? ["sqs:SendMessage"] : ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource = aws_sqs_queue.ask.arn }] })
}
resource "aws_lambda_event_source_mapping" "ask" {
  event_source_arn        = aws_sqs_queue.ask.arn
  function_name           = aws_lambda_function.app["ask"].arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]
  depends_on              = [aws_iam_role_policy.queue]
}
resource "aws_scheduler_schedule_group" "sync" {
  name = local.prefix
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.prefix}-scheduler"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole", Condition = { StringEquals = { "aws:SourceAccount" = local.account }, ArnEquals = { "aws:SourceArn" = aws_scheduler_schedule_group.sync.arn } } }] })
}
resource "aws_iam_role_policy" "scheduler" {
  role   = aws_iam_role.scheduler.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = aws_lambda_function.app["sync"].arn }] })
}
resource "aws_scheduler_schedule" "sync" {
  name                = "${local.prefix}-sync"
  group_name          = aws_scheduler_schedule_group.sync.name
  schedule_expression = "rate(1 minute)"
  state               = var.sync_enabled ? "ENABLED" : "DISABLED"
  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.app["sync"].arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ source = "schedule" })
    retry_policy {
      maximum_event_age_in_seconds = 60
      maximum_retry_attempts       = 0
    }

  }

}

resource "aws_iam_role" "training" {
  for_each           = toset(["states", "sagemaker", "bedrock"])
  name               = "${local.prefix}-${each.key}"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "${each.key}.amazonaws.com" }, Action = "sts:AssumeRole", Condition = { StringEquals = { "aws:SourceAccount" = local.account }, ArnLike = { "aws:SourceArn" = "arn:aws:${each.key}:us-east-2:${local.account}:${each.key == "states" ? "stateMachine:${local.prefix}-training" : each.key == "sagemaker" ? "training-job/${local.prefix}-*" : "model-import-job/*"}" } } }] })
}
resource "aws_iam_role_policy" "training_s3" {
  for_each = toset(["sagemaker", "bedrock"])
  role     = aws_iam_role.training[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket", "s3:GetBucketLocation"], Resource = aws_s3_bucket.data["artifacts"].arn },
    { Effect = "Allow", Action = each.key == "bedrock" ? ["s3:GetObject"] : ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.data["artifacts"].arn}/training/*" }
  ] })
}
resource "aws_sfn_state_machine" "training" {
  name       = "${local.prefix}-training"
  role_arn   = aws_iam_role.training["states"].arn
  definition = var.state_machine_definition != "" ? var.state_machine_definition : local.training_definition
}

resource "aws_iam_role_policy" "box_secret" {
  for_each = toset(["api", "sync"])
  role     = aws_iam_role.lambda[each.key].id
  policy   = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = data.aws_secretsmanager_secret.box.arn }] })
}
