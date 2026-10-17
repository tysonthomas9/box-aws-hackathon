output "url" {
  value = "https://${aws_cloudfront_distribution.app.domain_name}"
}

output "distribution_id" {
  value = aws_cloudfront_distribution.app.id
}

output "api_endpoint" {
  value = aws_apigatewayv2_api.app.api_endpoint
}

output "artifact_bucket" {
  value = aws_s3_bucket.data["artifacts"].id
}

output "web_bucket" {
  value = aws_s3_bucket.data["web"].id
}

output "tables" {
  value = { for key, table in aws_dynamodb_table.records : key => table.name
  }
}

output "origin_secret_id" {
  value = aws_secretsmanager_secret.app["origin"].arn
}

output "training_roles" {
  value = { for key, role in aws_iam_role.training : key => role.arn
  }
}

output "training_state_machine_arn" {
  value = aws_sfn_state_machine.training.arn
}

output "ask_queue_url" {
  value = aws_sqs_queue.ask.url
}
