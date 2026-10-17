# Snapshot objects are written once with If-None-Match; readers resolve their
# immutable DynamoDB hash pointer without loading Box/model clients.
locals {
  extraction_snapshot_roles = {
    api             = { id = aws_iam_role.lambda["api"].id, write = true }
    sync            = { id = aws_iam_role.lambda["sync"].id, write = true }
    ask             = { id = aws_iam_role.lambda["ask"].id, write = false }
    training_worker = { id = aws_iam_role.training_worker.id, write = false }
  }
}

resource "aws_iam_role_policy" "extraction_snapshots" {
  for_each = local.extraction_snapshot_roles
  role     = each.value.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = each.value.write ? ["s3:GetObject", "s3:PutObject"] : ["s3:GetObject"], Resource = "${aws_s3_bucket.data["artifacts"].arn}/extraction/snapshots/*" },
    { Effect = "Allow", Action = ["dynamodb:GetItem"], Resource = aws_dynamodb_table.records["items"].arn }
  ] })
}

resource "aws_iam_role_policy" "extraction_rows" {
  for_each = toset(["api", "sync"])
  role     = aws_iam_role.lambda[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:BatchWriteItem"], Resource = aws_dynamodb_table.records["items"].arn }
  ] })
}
