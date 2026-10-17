# The schedule stays off during initial corpus ingestion; enable after the handoff.
variable "sync_enabled" {
  type    = bool
  default = false
}

locals {
  web_handlers = {
    api        = "lambdas.api.handler"
    sync       = "lambdas.sync.handler"
    ask        = "lambdas.ask_worker.handler"
    evaluation = "kloop.eval.runtime.handler"
  }
  web_runtime_env = {
    KLOOP_PUBLIC_ORIGIN      = "https://${aws_cloudfront_distribution.app.domain_name}"
    KLOOP_EXTRACTION_FACTORY = "kloop.extract.runtime:factory"
    KLOOP_TRAINING_FACTORY   = "kloop.train.runtime:service"
    KLOOP_BASE_MODEL_ID      = var.base_import_arn
    KLOOP_BOX_FOLDER_ID      = var.box_folder_id
    KLOOP_REVIEW_MODE        = "exceptions"
    KLOOP_SYNC_FUNCTION_NAME = "${local.prefix}-sync"
  }
}

resource "aws_iam_role_policy" "web_jobs" {
  for_each = toset(["api", "ask"])
  role     = aws_iam_role.lambda[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"], Resource = aws_dynamodb_table.records["ask_jobs"].arn }
  ] })
}

resource "aws_iam_role_policy" "web_reads" {
  role = aws_iam_role.lambda["api"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:Query"], Resource = [for key in ["items", "versions", "sync_cursors"] : aws_dynamodb_table.records[key].arn] },
    { Effect = "Allow", Action = ["dynamodb:UpdateItem"], Resource = aws_dynamodb_table.records["webhook_dedupe"].arn }
  ] })
}

resource "aws_iam_role_policy" "sync_state" {
  for_each = toset(["api", "sync"])
  role     = aws_iam_role.lambda[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:UpdateItem", "dynamodb:Query"], Resource = [aws_dynamodb_table.records["sync_cursors"].arn, aws_dynamodb_table.records["webhook_dedupe"].arn] },
    { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = aws_lambda_function.app["sync"].arn }
  ] })
}

resource "aws_iam_role_policy" "ask_models" {
  role = aws_iam_role.lambda["ask"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = concat(
    var.base_import_arn == "" ? [] : [{ Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = var.base_import_arn }],
    [{ Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = local.imported_model_arn, Condition = { StringEquals = { "aws:ResourceTag/deployment" = local.prefix } } },
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = data.aws_secretsmanager_secret.box.arn }]
  ) })
}

resource "aws_iam_role_policy" "extraction_fallback" {
  for_each = toset(["api", "sync"])
  role     = aws_iam_role.lambda[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = "arn:aws:bedrock:us-east-2::foundation-model/zai.glm-5" }
  ] })
}
