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

  # Enabled AFTER the first apply. The sequence that got us here:
  #   1. terraform init && terraform apply   (local state; created bucket + table)
  #   2. uncomment this block, filling in the outputs
  #   3. terraform init -migrate-state       (moved local state into S3)
  #
  # LOCKING: use_lockfile, not dynamodb_table.
  #
  # This stack originally used a DynamoDB lock table (commit 8b93713) because
  # that was the canonical pattern for a decade. Terraform 1.15 warns on every
  # plan that "dynamodb_table" is deprecated in favour of "use_lockfile".
  #
  # use_lockfile makes the S3 backend take a lock via S3's own conditional
  # writes (PutObject with If-None-Match, available since Aug 2024). It writes
  # a .tflock object next to the state file. Same mutual exclusion, one fewer
  # resource, one fewer IAM policy, and no DynamoDB dependency at all.
  #
  # The lock table was destroyed in the commit that introduced this comment.
  # Its construction is preserved in git history rather than in dead
  # infrastructure.
  backend "s3" {
    bucket       = "tg-agent-tfstate-81b4d8bc"
    key          = "bootstrap/terraform.tfstate"
    region       = "eu-central-1"
    use_lockfile = true
    encrypt      = true
  }
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

# S3 bucket names occupy a single global namespace, so the name needs an
# account-specific component to avoid colliding with a stranger's bucket.
data "aws_caller_identity" "current" {}

locals {
  # DERIVED FROM the account id, but deliberately not the account id itself.
  #
  # The obvious choice is to suffix the bucket with the raw account id. The
  # problem: the resulting bucket name is committed verbatim into the backend
  # block of every stack in this repo, and this repo is going to be public.
  # AWS account ids are not secrets, but publishing one hands an attacker a
  # confirmed live target for role-name enumeration and support-desk social
  # engineering, for no benefit whatsoever.
  #
  # A truncated SHA-256 keeps the name deterministic — the same account always
  # resolves to the same bucket, so the committed backend block stays valid —
  # while leaking nothing. 8 hex chars is ~4 billion values, ample given the
  # name is already namespaced by var.project.
  account_hash = substr(sha256(data.aws_caller_identity.current.account_id), 0, 8)
}

###############################################################################
# State bucket
###############################################################################

resource "aws_s3_bucket" "state" {
  bucket = "${var.project}-tfstate-${local.account_hash}"

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
# Locking — no resource required
###############################################################################

# There is deliberately no lock table here.
#
# S3 historically had no compare-and-swap primitive, so two people running
# `apply` at once could both read the same state, both write, and the second
# would silently clobber the first. Terraform's answer was a DynamoDB table
# with a conditional write on a hash key: whoever won the PutItem held the
# lock. That table also stored a "<key>-md5" digest item, which the backend
# used to detect a state file that had been corrupted or truncated between
# writes.
#
# In Aug 2024 S3 gained conditional writes (PutObject with If-None-Match), and
# Terraform 1.10 exposed them as `use_lockfile`. The backend now takes the lock
# by writing a .tflock object beside the state file. Same mutual exclusion,
# one fewer resource, one fewer IAM policy, no second service in the critical
# path of every apply.
#
# This stack built the DynamoDB table first (commit 8b93713) and destroyed it
# once Terraform 1.15 flagged `dynamodb_table` as deprecated on every plan.
# Keeping it would have meant either a permanent warning in plan output or an
# unreferenced table sitting in the account. The construction is preserved in
# git history, which is the right place for it.
