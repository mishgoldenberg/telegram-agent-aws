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
    Bot token from @BotFather. Supplied via terraform.tfvars, which is
    gitignored, and stored as an SSM SecureString.

    Note that it also lands in Terraform state, which is why the state bucket
    is private, encrypted and versioned. State is a secret-bearing artefact —
    treat it as one.
  EOT
  type        = string
  sensitive   = true
}

variable "telegram_user_id" {
  description = "Numeric Telegram user id allowed to use the bot. Everyone else is ignored."
  type        = string
}

variable "alert_emails" {
  description = "Recipients for budget and CloudWatch alarms."
  type        = list(string)
  default     = ["golden.mihel@gmail.com"]
}
