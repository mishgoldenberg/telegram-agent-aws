###############################################################################
# envs/dev — the ingest pipeline.
#
# DIRECTORIES RATHER THAN WORKSPACES, and this gets asked about.
#
# Workspaces share one backend configuration and one set of credentials. dev
# and prod would live in the same bucket under env:/, a `terraform apply` in
# the wrong workspace is one forgotten `select` away, and the two environments
# cannot diverge structurally without count/for_each hacks smeared through the
# code.
#
# Directories give separate state files, separate backend configs, and a clean
# path to separate AWS ACCOUNTS later, which is the real production answer.
# Workspaces are for short-lived parallel copies of the same config — a
# per-PR ephemeral stack — not for environment separation.
###############################################################################

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "s3" {
    bucket       = "tg-agent-tfstate-81b4d8bc"
    key          = "envs/dev/terraform.tfstate"
    region       = "eu-central-1"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region

  # Applied to every resource this provider creates. Requirement: tag
  # everything for cost attribution. Doing it here rather than per-resource
  # means it cannot be forgotten on a resource added later.
  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = var.owner
      Repo        = "mishgoldenberg/telegram-agent-aws"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  # Same derivation as the bootstrap: unique per account, but the account id
  # itself never reaches a committed file or a public repo.
  account_hash = substr(sha256(data.aws_caller_identity.current.account_id), 0, 8)
}

###############################################################################
# Secrets
###############################################################################

# The webhook path. Unguessable so the endpoint is not discoverable by scanning,
# but this is obscurity layered on authentication, never instead of it — the
# ingest Lambda verifies Telegram's secret-token header on every request.
resource "random_id" "webhook_path" {
  byte_length = 16
}

# The value Telegram echoes back in X-Telegram-Bot-Api-Secret-Token. Generated
# here rather than chosen by a human: it never needs to be memorable, and a
# human-chosen value would be weaker.
resource "random_password" "webhook_secret" {
  length  = 48
  special = false # Telegram restricts this header to A-Z a-z 0-9 _ -
}

# SSM PARAMETER STORE, NOT SECRETS MANAGER.
#
# Secrets Manager is $0.40 per secret per month. Three secrets is $1.20/month —
# 24% of the entire $5 budget, for storage of a few hundred bytes.
#
# Parameter Store Standard is free, encrypts SecureString with a KMS
# AWS-managed key, and is read the same way from Lambda. What it gives up is
# native rotation and cross-account resource policies. Nothing here rotates,
# and there is one account. At production scale with real rotation
# requirements, Secrets Manager earns its price.
resource "aws_ssm_parameter" "bot_token" {
  name        = "/${var.project}/${var.environment}/bot_token"
  description = "Telegram bot token from @BotFather"
  type        = "SecureString"
  value       = var.telegram_bot_token

  tags = { Component = "secrets" }
}

resource "aws_ssm_parameter" "webhook_secret" {
  name        = "/${var.project}/${var.environment}/webhook_secret"
  description = "Shared secret Telegram sends in X-Telegram-Bot-Api-Secret-Token"
  type        = "SecureString"
  value       = random_password.webhook_secret.result

  tags = { Component = "secrets" }
}

###############################################################################
# Data plane
###############################################################################

module "state_table" {
  source = "../../modules/state-table"

  project     = var.project
  environment = var.environment
}

module "job_queue" {
  source = "../../modules/job-queue"

  project     = var.project
  environment = var.environment

  # Generous, because the consumer is a local GPU doing Whisper plus an LLM
  # turn. Too short and a slow job is delivered twice and answered twice.
  visibility_timeout_seconds = 300
}

###############################################################################
# Lambdas
#
# Each gets its own role with exactly the statements it needs. Note what is
# ABSENT as much as what is present: audio_event has no DynamoDB access and no
# SSM access, because it needs neither.
###############################################################################

module "fn_audio_event" {
  source = "../../modules/lambda-fn"

  project     = var.project
  environment = var.environment
  name        = "audio-event"
  source_dir  = "${path.module}/../../lambdas/audio_event"

  # Same account concurrency-limit constraint as fn_ingest below; see the long
  # comment there. This function is not internet-facing (only S3 invokes it),
  # so the ceiling matters less here regardless.
  reserved_concurrency = -1

  environment_variables = {
    QUEUE_URL = module.job_queue.url
  }

  policy_statements = [
    {
      Sid      = "ReadVoiceObjectMetadata"
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "arn:aws:s3:::${var.project}-${var.environment}-audio-${local.account_hash}/voice/*"
    },
    {
      Sid      = "EnqueueTranscriptionJob"
      Effect   = "Allow"
      Action   = ["sqs:SendMessage"]
      Resource = module.job_queue.arn
    },
  ]
}

module "audio_bucket" {
  source = "../../modules/audio-bucket"

  project     = var.project
  environment = var.environment
  name_suffix = local.account_hash
  account_id  = data.aws_caller_identity.current.account_id

  expire_after_days = 7

  notify_lambda_arn  = module.fn_audio_event.arn
  notify_lambda_name = module.fn_audio_event.name
}

module "fn_ingest" {
  source = "../../modules/lambda-fn"

  project     = var.project
  environment = var.environment
  name        = "ingest"
  source_dir  = "${path.module}/../../lambdas/ingest"

  # Downloading a voice note from Telegram is the slowest thing this does.
  timeout_seconds = 20

  # RESERVED CONCURRENCY IS DISABLED, AND NOT BECAUSE IT IS UNWANTED.
  #
  # This account's total Lambda concurrency limit is 10 (new accounts start
  # there, not at the classic 1000). AWS refuses any reservation that would
  # push UnreservedConcurrentExecutions below 10, so with a ceiling of exactly
  # 10 no reservation is possible at all:
  #
  #   InvalidParameterValueException: Specified ReservedConcurrentExecutions
  #   for function decreases account's UnreservedConcurrentExecution below its
  #   minimum value of [10]
  #
  # The account ceiling currently provides the same protection, more tightly
  # than the reservation would have. The danger is that it is implicit: AWS
  # raises this limit as an account matures, and when it does, this function
  # silently becomes able to scale to the new ceiling.
  #
  # API Gateway throttling (2 req/s, burst 5) is unaffected and remains the
  # primary rate control.
  #
  # TODO: once `aws lambda get-account-settings` reports ConcurrentExecutions
  # above ~100, set this back to 5.
  reserved_concurrency = -1

  environment_variables = {
    TABLE_NAME      = module.state_table.name
    QUEUE_URL       = module.job_queue.url
    AUDIO_BUCKET    = module.audio_bucket.name
    AUDIO_PREFIX    = module.audio_bucket.object_prefix
    SSM_PREFIX      = "/${var.project}/${var.environment}"
    ALLOWED_USER_ID = var.telegram_user_id
  }

  policy_statements = [
    {
      Sid    = "ReadOwnSecrets"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      # Scoped to this project and environment's parameter path only. Not
      # ssm:* and not "*" — this role cannot read prod's bot token.
      Resource = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project}/${var.environment}/*"
    },
    {
      Sid    = "DecryptSecureStrings"
      Effect = "Allow"
      Action = ["kms:Decrypt"]
      # The AWS-managed SSM key. Required because SecureString values are
      # KMS-encrypted; GetParameter alone returns ciphertext.
      Resource = "arn:aws:kms:${var.region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"
    },
    {
      Sid    = "WriteDedupeMarker"
      Effect = "Allow"
      # PutItem only. Not GetItem, not Query, not DeleteItem. This function
      # writes idempotency markers and never reads conversation history.
      Action   = ["dynamodb:PutItem"]
      Resource = module.state_table.arn
    },
    {
      Sid      = "EnqueueTextJob"
      Effect   = "Allow"
      Action   = ["sqs:SendMessage"]
      Resource = module.job_queue.arn
    },
    {
      Sid    = "StoreVoiceNote"
      Effect = "Allow"
      # PutObject only, and only under the voice/ prefix. This function cannot
      # read back what it wrote, cannot delete, and cannot list the bucket.
      Action   = ["s3:PutObject"]
      Resource = "${module.audio_bucket.arn}/voice/*"
    },
  ]
}

module "http_api" {
  source = "../../modules/http-api"

  project     = var.project
  environment = var.environment

  lambda_invoke_arn    = module.fn_ingest.invoke_arn
  lambda_function_name = module.fn_ingest.name
  webhook_path         = random_id.webhook_path.hex

  throttle_rate_limit  = 2
  throttle_burst_limit = 5
}

###############################################################################
# The local worker's identity
###############################################################################

# THE ONE LONG-LIVED CREDENTIAL IN THIS BUILD, AND IT IS A KNOWN COMPROMISE.
#
# The worker runs on a home PC and must authenticate non-interactively, so
# Identity Center (which needs a browser) does not fit. That leaves an IAM user
# with an access key.
#
# The mitigations: the policy below is scoped to exactly one queue, one bucket
# prefix and one table, so a leak grants an attacker the ability to read this
# assistant's job queue and nothing else in the account. No console access, no
# ability to create anything.
#
# The proper fix is IAM Roles Anywhere with a self-signed CA as trust anchor —
# free, no ACM Private CA needed, and it gives the worker short-lived
# certificate-derived credentials. That is the planned upgrade and is written
# up in the README rather than quietly omitted.
resource "aws_iam_user" "worker" {
  name = "${var.project}-${var.environment}-worker"
  path = "/service/"

  tags = { Component = "worker-identity" }
}

resource "aws_iam_access_key" "worker" {
  user = aws_iam_user.worker.name
}

data "aws_iam_policy_document" "worker" {
  statement {
    sid    = "ConsumeJobs"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ChangeMessageVisibility",
    ]
    resources = [module.job_queue.arn]
  }

  statement {
    sid       = "ReadVoiceNotes"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${module.audio_bucket.arn}/voice/*"]
  }

  statement {
    sid    = "ManageConversationState"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
    ]
    resources = [module.state_table.arn]
  }

  statement {
    sid       = "ReadBotToken"
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project}/${var.environment}/bot_token"]
  }

  statement {
    sid       = "DecryptSecureStrings"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"]
  }
}

resource "aws_iam_user_policy" "worker" {
  name   = "worker"
  user   = aws_iam_user.worker.name
  policy = data.aws_iam_policy_document.worker.json
}

###############################################################################
# Guardrails
###############################################################################

module "observability" {
  source = "../../modules/observability"

  project     = var.project
  environment = var.environment

  alert_emails = var.alert_emails

  queue_name = module.job_queue.name
  dlq_name   = module.job_queue.dlq_name

  # This PC never sleeps (verified: STANDBYIDLE = 0 on AC and DC), so five
  # minutes of backlog genuinely means something is wrong.
  queue_age_threshold_seconds = 300

  lambda_function_names = [module.fn_ingest.name, module.fn_audio_event.name]
  ingest_function_name  = module.fn_ingest.name
}

module "budget" {
  source = "../../modules/budget"

  project      = var.project
  limit_usd    = "5"
  alert_emails = var.alert_emails

  # Left false until the Project cost-allocation tag shows Active in Billing.
  # A tag-filtered budget reports $0 before activation, which looks like
  # success and is actually blindness.
  scope_to_project_tag = false
}
