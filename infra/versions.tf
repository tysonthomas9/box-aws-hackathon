terraform {
  required_version = ">= 1.10, < 2.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.7" }
  }
  backend "s3" {}
}
provider "aws" {
  region  = "us-east-2"
  profile = var.aws_profile
  default_tags {
    tags = { project = "box-hackathon", deployment = var.name_prefix, managed_by = "terraform" }
  }
}
data "aws_caller_identity" "current" {
}
variable "aws_profile" {
  default = "box-hackathon"
}
variable "name_prefix" {
  default = "kloop"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.name_prefix))
    error_message = "Use 3-25 lowercase letters, numbers or hyphens, beginning with a letter."
  }
}
variable "state_machine_definition" {
  type    = string
  default = ""
}
locals {
  account     = data.aws_caller_identity.current.account_id
  prefix      = var.name_prefix
  functions   = toset(["api", "sync", "ask", "training", "evaluation"])
  collections = toset(["items", "reviews", "versions", "ask_jobs", "sync_cursors", "webhook_dedupe", "cleanup_ledger"])
}
