###############################################################################
# bootstrap/ — creates the Terraform remote state backend.
#
# THE CHICKEN-AND-EGG PROBLEM
# ---------------------------
# Every other stack in this repo stores its state in S3. But the S3 bucket and
# the lock table are themselves Terraform resources, and they cannot store
# their own state in a bucket that does not exist yet.
#
# The resolution: this stack runs ONCE with LOCAL state, creates the backend,
# then migrates its own state into the backend it just built. After migration,
# bootstrap/terraform.tfstate is empty and the real state lives in S3 like
# everything else.
#
# The alternative is to create the bucket by hand in the console and reference
# it. That works, but then the backend is the one piece of infrastructure not
# described in code, which defeats the point. Bootstrapping in Terraform and
# migrating is the standard resolution and is worth being able to explain.
###############################################################################

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # DELIBERATELY COMMENTED OUT ON FIRST RUN.
  #
  # Run order:
  #   1. terraform init && terraform apply   (local state; creates bucket + table)
  #   2. uncomment this block, filling in the two outputs
  #   3. terraform init -migrate-state       (moves local state into S3)
  #
  # backend "s3" {
  #   bucket         = "REPLACE_WITH_state_bucket_name_OUTPUT"
  #   key            = "bootstrap/terraform.tfstate"
  #   region         = "eu-central-1"
  #   dynamodb_table = "REPLACE_WITH_lock_table_name_OUTPUT"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.region

  # Applied to every resource this provider creates, so cost attribution can
  # never be forgotten on an individual resource. Requirement 5.
  default_tags {
    tags = local.common_tags
  }
}

locals {
  common_tags = {
    Project     = var.project
    Environment = "shared" # the backend is shared by dev and prod
    Component   = "tf-backend"
    ManagedBy   = "terraform"
    Owner       = var.owner
  }
}

# Used to make the bucket name globally unique without hardcoding an account id
# into the repo. S3 bucket names are a single global namespace.
data "aws_caller_identity" "current" {}

###############################################################################
# State bucket
###############################################################################

resource "aws_s3_bucket" "state" {
  bucket = "${var.project}-tfstate-${data.aws_caller_identity.current.account_id}"

  # State is the one thing here that must never be casually destroyed. Losing
  # it means Terraform forgets every resource it manages, and a fresh apply
  # would try to recreate infrastructure that already exists.
  lifecycle {
    prevent_destroy = true
  }
}

# Versioning is not optional for a state bucket. A corrupted or truncated state
# push is recoverable only if the previous version is still retrievable.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

# SSE-S3 (AES256), not SSE-KMS with a customer-managed key.
#
# A CMK costs $1/month plus per-request charges — 20% of the $5 budget. SSE-S3
# is free and still encrypts at rest. At production scale the answer flips: a
# CMK gives an auditable key policy, per-key CloudTrail, and the ability to
# deny access at the key even to principals holding s3:GetObject.
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# State files contain resource attributes in plaintext, which routinely include
# values you would not publish. This bucket must never be public.
resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Versioning without expiry grows forever: every apply writes a new version, so
# an active repo accumulates thousands. 90 days is long enough to recover from
# a bad push while keeping storage negligible.
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "expire-noncurrent-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.state]
}

# Reject any plaintext (non-TLS) request. Without this the bucket accepts
# http:// as readily as https://.
resource "aws_s3_bucket_policy" "state_tls_only" {
  bucket = aws_s3_bucket.state.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.state.arn,
        "${aws_s3_bucket.state.arn}/*",
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })

  # Must land after the public access block, or the Deny-with-Principal-"*"
  # policy can trip the block-public-policy evaluation during creation.
  depends_on = [aws_s3_bucket_public_access_block.state]
}

###############################################################################
# Lock table
###############################################################################

# WHY THIS EXISTS, AND WHY IT IS NOW LEGACY
# -----------------------------------------
# S3 historically had no compare-and-swap primitive, so two people running
# `apply` at once could both read the same state, both write, and the second
# would silently clobber the first. Terraform's answer was a DynamoDB table
# with a conditional write on a hash key: whoever wins the PutItem holds the
# lock.
#
# As of Terraform 1.10 the S3 backend supports `use_lockfile = true`, which
# uses S3's own conditional writes (added Aug 2024) and removes the need for
# this table entirely. This build creates the table deliberately, because
# understanding why it existed is the point of the exercise.
#
# The interview answer: "I built the DynamoDB lock table, and I know it's
# superseded by S3 native locking in 1.10+. I'd use use_lockfile on a new
# project — one less resource, one less IAM policy, no extra cost."
#
# PROVISIONED, not on-demand: the DynamoDB always-free tier covers 25 WCU and
# 25 RCU but does NOT cover on-demand request pricing. A lock table sees a
# handful of writes per apply, so 1/1 is ample and costs nothing.
resource "aws_dynamodb_table" "lock" {
  name           = "${var.project}-tflock"
  billing_mode   = "PROVISIONED"
  read_capacity  = 1
  write_capacity = 1

  # Terraform requires the hash key to be exactly "LockID". Not configurable.
  hash_key = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  # Free, and allows recovery if the table is deleted or corrupted.
  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true # AWS-owned key, no charge
  }

  lifecycle {
    prevent_destroy = true
  }
}
