variable "project" {
  description = "Project slug; prefixes every resource name and is the cost-allocation tag."
  type        = string
  default     = "tg-agent"
}

variable "environment" {
  description = "Environment name."
  type        = string
  default     = "dev"
}

variable "region" {
  description = "AWS region. eu-central-1: see bootstrap/variables.tf for the reasoning."
  type        = string
  default     = "eu-central-1"
}

variable "owner" {
  description = "Owner cost-allocation tag."
  type        = string
  default     = "mishgoldenberg"
}

variable "telegram_bot_token" {
  description = <<-EOT
    Bot token from @BotFather.

    Used ONLY when the SSM parameter is first created. The parameter carries
    ignore_changes = [value], so later applies never read or rewrite it, and
    CI does not need the real token at all - see the comment on the resource.

    The placeholder default is what CI passes. It is never written to an
    existing parameter. On a genuinely fresh environment, set the real value
    out of band immediately after the first apply:

      aws ssm put-parameter --name /tg-agent/<env>/bot_token \
        --value <token> --type SecureString --overwrite

    The value still enters Terraform state on first create, which is why the
    state bucket is private, encrypted and versioned. State is a
    secret-bearing artefact and should be treated as one.
  EOT
  type        = string
  sensitive   = true
  default     = "set-out-of-band-see-variable-description"
}

variable "telegram_user_id" {
  description = <<-EOT
    Numeric Telegram user id allowed to use the bot. Everyone else is ignored.

    Not a secret - it is a Lambda environment variable, readable in the console
    by anyone with access to the account - so it lives in tfvars locally and in
    a GitHub repository VARIABLE (not a secret) for CI.

    DELIBERATELY NO DEFAULT. An earlier draft defaulted it to "0", which would
    have let a CI apply silently set the allowlist to a user id that does not
    exist - the bot would accept nothing, answer nobody, and look merely
    broken. A missing value must fail the apply loudly instead.
  EOT
  type        = string

  validation {
    condition     = can(regex("^[1-9][0-9]{5,}$", var.telegram_user_id))
    error_message = "Must be a real numeric Telegram user id. '0' and empty are rejected on purpose - see the description."
  }
}

variable "alert_emails" {
  description = "Recipients for budget and CloudWatch alarms."
  type        = list(string)
  default     = ["golden.mihel@gmail.com"]
}
