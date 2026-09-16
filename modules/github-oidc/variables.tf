variable "project" {
  description = "Project slug; prefixes role names and scopes the IAM resource ARNs."
  type        = string
}

variable "account_id" {
  description = "Account id, used to build the role ARNs the apply role may manage."
  type        = string
}

variable "github_repo" {
  description = <<-EOT
    owner/name of the repository allowed to assume these roles.

    This value IS the security boundary - it goes into the sub condition of
    both trust policies. Get it wrong and either nothing works, or something
    other than your repository can deploy to your account.
  EOT
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repo))
    error_message = "Must be exactly owner/name, e.g. mishgoldenberg/telegram-agent-aws - no URL, no trailing slash."
  }
}

variable "default_branch" {
  description = "Branch whose pushes may run apply. Anything else gets plan only."
  type        = string
  default     = "main"
}

variable "state_bucket_arn" {
  description = "ARN of the Terraform state bucket. Both roles need it; a plan writes the lock object."
  type        = string
}
