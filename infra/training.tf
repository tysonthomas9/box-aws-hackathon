# Standard workflow and runtime wiring. No live training occurs on apply.
variable "training_base_model_id" {
  type    = string
  default = "Qwen/Qwen3-4B-Instruct-2507"
}
variable "training_base_s3_uri" {
  type    = string
  default = "s3://box-hackathon-poc1-base-20261017-549803795565/base/"
}
variable "training_instance_type" {
  type    = string
  default = "ml.g5.2xlarge"
  validation {
    condition     = contains(["ml.g5.2xlarge", "ml.g6.2xlarge"], var.training_instance_type)
    error_message = "Select the approved g5 or g6 training instance."
  }
}
variable "training_hyperparameters" {
  type = object({ epochs = number, learning_rate = number, seed = number, max_length = number, gradient_accumulation = number, minimum_gain = number })
  default = {
    epochs                = 3, learning_rate = 0.0002, seed = 17, max_length = 512,
    gradient_accumulation = 4, minimum_gain = 0.05
  }
}
variable "base_import_arn" {
  type    = string
  default = ""
}
variable "box_folder_id" {
  type    = string
  default = ""
}
variable "box_reports_folder_id" {
  type    = string
  default = ""
}
locals {
  training_definition  = templatefile("${path.module}/training.asl.json", { worker_arn = aws_lambda_function.training_worker.arn })
  training_base_bucket = split("/", trimprefix(var.training_base_s3_uri, "s3://"))[0]
  training_job_arn     = "arn:aws:sagemaker:us-east-2:${local.account}:training-job/${local.prefix}-*"
  import_job_arn       = "arn:aws:bedrock:us-east-2:${local.account}:model-import-job/*"
  imported_model_arn   = "arn:aws:bedrock:us-east-2:${local.account}:imported-model/*"
  training_env = merge({
    KLOOP_TRAIN_DEPLOYMENT     = local.prefix
    KLOOP_TRAIN_BASE_MODEL_ID  = var.training_base_model_id
    KLOOP_TRAIN_BASE_S3_URI    = var.training_base_s3_uri
    KLOOP_TRAIN_INSTANCE_TYPE  = var.training_instance_type
    KLOOP_BASE_MODEL_ID        = var.base_import_arn
    KLOOP_REPORTS_FOLDER_ID    = var.box_reports_folder_id
    KLOOP_TRAINING_ARN         = "arn:aws:states:us-east-2:${local.account}:stateMachine:${local.prefix}-training"
    KLOOP_BOX_FOLDER_ID        = var.box_folder_id
    KLOOP_ARTIFACT_BUCKET      = aws_s3_bucket.data["artifacts"].id
    KLOOP_VERSIONS_TABLE       = aws_dynamodb_table.records["versions"].name
    KLOOP_ASK_JOBS_TABLE       = aws_dynamodb_table.records["ask_jobs"].name
    KLOOP_ITEMS_TABLE          = aws_dynamodb_table.records["items"].name
    KLOOP_CLEANUP_LEDGER_TABLE = aws_dynamodb_table.records["cleanup_ledger"].name
    KLOOP_SAGEMAKER_ROLE       = aws_iam_role.training["sagemaker"].arn
    KLOOP_IMPORT_ROLE          = aws_iam_role.training["bedrock"].arn
    KLOOP_BOX_SECRET_ID        = data.aws_secretsmanager_secret.box.arn
    KLOOP_EVALUATION_FUNCTION  = "arn:aws:lambda:us-east-2:${local.account}:function:${local.prefix}-evaluation"
  }, { for key, value in var.training_hyperparameters : "KLOOP_TRAIN_${upper(key)}" => tostring(value) })
}

resource "aws_iam_role" "training_worker" {
  name = "${local.prefix}-training-worker"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}
resource "aws_cloudwatch_log_group" "training_worker" {
  name              = "/aws/lambda/${local.prefix}-training-worker"
  retention_in_days = 7
}
resource "aws_lambda_function" "training_worker" {
  function_name    = "${local.prefix}-training-worker"
  role             = aws_iam_role.training_worker.arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "kloop.train.runtime.handler"
  s3_bucket        = aws_s3_object.lambda.bucket
  s3_key           = aws_s3_object.lambda.key
  source_code_hash = filebase64sha256("${path.module}/../.build/lambda.zip")
  timeout          = 900
  memory_size      = 1024
  environment {
    variables = local.training_env
  }
  depends_on = [aws_iam_role_policy.training_worker]
}
resource "aws_iam_role_policy" "training_worker" {
  role = aws_iam_role.training_worker.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.training_worker.arn}:*" },
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:ConditionCheckItem"], Resource = [for key in ["items", "versions", "cleanup_ledger"] : aws_dynamodb_table.records[key].arn] },
    { Effect = "Allow", Action = ["dynamodb:Query"], Resource = aws_dynamodb_table.records["ask_jobs"].arn },
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.data["artifacts"].arn },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.data["artifacts"].arn}/training/*" },
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = data.aws_secretsmanager_secret.box.arn },
    { Effect = "Allow", Action = ["bedrock:ListImportedModels"], Resource = "*" },
    { Effect = "Allow", Action = ["bedrock:CreateModelImportJob"], Resource = "*" },
    { Effect = "Allow", Action = ["bedrock:GetModelImportJob"], Resource = local.import_job_arn },
    { Effect = "Allow", Action = ["bedrock:TagResource"], Resource = [local.import_job_arn, local.imported_model_arn] },
    { Effect = "Allow", Action = ["bedrock:DeleteImportedModel", "bedrock:ListTagsForResource"], Resource = local.imported_model_arn },
    { Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = [local.imported_model_arn, "arn:aws:bedrock:us-east-2::foundation-model/zai.glm-5", "arn:aws:bedrock:us-east-2:${local.account}:inference-profile/us.moonshotai.kimi-k3", "arn:aws:bedrock:us-*::foundation-model/moonshotai.kimi-k3"] },
    { Effect = "Allow", Action = ["sagemaker:DescribeTrainingJob", "sagemaker:StopTrainingJob"], Resource = local.training_job_arn },
    { Effect = "Allow", Action = ["iam:PassRole"], Resource = aws_iam_role.training["bedrock"].arn, Condition = { StringEquals = { "iam:PassedToService" = "bedrock.amazonaws.com" } } },
    { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = "arn:aws:lambda:us-east-2:${local.account}:function:${local.prefix}-evaluation" },
    { Effect = "Allow", Action = ["states:DescribeExecution"], Resource = "arn:aws:states:us-east-2:${local.account}:execution:${local.prefix}-training:*" }
  ] })
}
resource "aws_iam_role_policy" "training_states" {
  role = aws_iam_role.training["states"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = aws_lambda_function.training_worker.arn },
    { Effect = "Allow", Action = ["sagemaker:CreateTrainingJob", "sagemaker:DescribeTrainingJob", "sagemaker:StopTrainingJob"], Resource = local.training_job_arn },
    { Effect = "Allow", Action = ["sagemaker:AddTags"], Resource = local.training_job_arn, Condition = { StringEquals = { "sagemaker:TaggingAction" = "CreateTrainingJob" } } },
    { Effect = "Allow", Action = ["iam:PassRole"], Resource = aws_iam_role.training["sagemaker"].arn, Condition = { StringEquals = { "iam:PassedToService" = "sagemaker.amazonaws.com" } } },
    { Effect = "Allow", Action = ["events:PutTargets", "events:PutRule", "events:DescribeRule"], Resource = "arn:aws:events:us-east-2:${local.account}:rule/StepFunctionsGetEventsForSageMakerTrainingJobsRule" }
  ] })
}
resource "aws_iam_role_policy" "training_start" {
  role = aws_iam_role.lambda["api"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["states:StartExecution"], Resource = aws_sfn_state_machine.training.arn },
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:Query"], Resource = [aws_dynamodb_table.records["versions"].arn, aws_dynamodb_table.records["items"].arn] }
  ] })
}
resource "aws_iam_role_policy" "sagemaker_runtime" {
  role = aws_iam_role.training["sagemaker"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket", "s3:GetBucketLocation"], Resource = "arn:aws:s3:::${local.training_base_bucket}" },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "arn:aws:s3:::${trimprefix(var.training_base_s3_uri, "s3://")}*" },
    { Effect = "Allow", Action = ["s3:PutObjectTagging", "s3:AbortMultipartUpload"], Resource = "${aws_s3_bucket.data["artifacts"].arn}/training/*" },
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"], Resource = "arn:aws:ecr:us-east-2:763104351884:repository/pytorch-training" },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "arn:aws:logs:us-east-2:${local.account}:log-group:/aws/sagemaker/TrainingJobs:log-stream:${local.prefix}-*" }
  ] })
}
resource "aws_cloudwatch_event_rule" "training_recovery" {
  name = "${local.prefix}-training-recovery"
  event_pattern = jsonencode({ source = ["aws.states"], "detail-type" = ["Step Functions Execution Status Change"], detail = {
    stateMachineArn = [aws_sfn_state_machine.training.arn], status = ["FAILED", "TIMED_OUT", "ABORTED"]
  } })
}
resource "aws_cloudwatch_event_target" "training_recovery" {
  rule = aws_cloudwatch_event_rule.training_recovery.name
  arn  = aws_lambda_function.training_worker.arn
  retry_policy {
    maximum_event_age_in_seconds = 21600
    maximum_retry_attempts       = 60
  }
}
resource "aws_lambda_permission" "training_recovery" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.training_worker.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.training_recovery.arn
}
resource "aws_iam_role" "evaluator_reader" {
  name               = "${local.prefix}-evaluator-reader"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { AWS = aws_iam_role.lambda["evaluation"].arn }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy" "evaluator_reader" {
  role = aws_iam_role.evaluator_reader.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.data["artifacts"].arn },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${aws_s3_bucket.data["artifacts"].arn}/sealed/*", "${aws_s3_bucket.data["artifacts"].arn}/training/*"] },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = ["${aws_s3_bucket.data["artifacts"].arn}/reports/*", "${aws_s3_bucket.data["artifacts"].arn}/sealed/reports/*", "${aws_s3_bucket.data["artifacts"].arn}/evaluations/*"] },
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"], Resource = aws_dynamodb_table.records["versions"].arn },
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = data.aws_secretsmanager_secret.box.arn },
    { Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = [local.imported_model_arn, "arn:aws:bedrock:us-east-2::foundation-model/zai.glm-5"] }
  ] })
}
resource "aws_iam_role_policy" "evaluation_assume" {
  role   = aws_iam_role.lambda["evaluation"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Resource = aws_iam_role.evaluator_reader.arn }] })
}

resource "aws_cloudwatch_event_rule" "training_expiry" {
  name                = "${local.prefix}-training-expiry"
  schedule_expression = "rate(5 minutes)"
}
resource "aws_cloudwatch_event_target" "training_expiry" {
  rule  = aws_cloudwatch_event_rule.training_expiry.name
  arn   = aws_lambda_function.training_worker.arn
  input = jsonencode({ recover_expired = true })
}
resource "aws_lambda_permission" "training_expiry" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.training_worker.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.training_expiry.arn
}
