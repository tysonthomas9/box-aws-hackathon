resource "aws_s3_bucket" "data" {
  for_each      = toset(["artifacts", "web"])
  bucket        = "${local.prefix}-${local.account}-${each.key}"
  force_destroy = true

}

resource "aws_s3_bucket_public_access_block" "data" {
  for_each                = aws_s3_bucket.data
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }

}

resource "aws_dynamodb_table" "records" {
  for_each     = local.collections
  name         = "${local.prefix}-${each.key}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"
  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  dynamic "ttl" {
    for_each = contains(["webhook_dedupe", "ask_jobs"], each.key) ? [1] : []
    content {
      attribute_name = "expires_at"
      enabled        = true
    }

  }

}

data "aws_secretsmanager_secret" "box" {
  name = "box-hackathon/box-ccg"
}

resource "aws_secretsmanager_secret" "app" {
  for_each                = toset(["auth", "cookie-signing", "origin"])
  name                    = "${local.prefix}/${each.key}"
  recovery_window_in_days = 0
}

# Approved exception: this origin guard is stored in encrypted private state.
resource "random_password" "origin" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret_version" "origin" {
  secret_id     = aws_secretsmanager_secret.app["origin"].id
  secret_string = random_password.origin.result
}
