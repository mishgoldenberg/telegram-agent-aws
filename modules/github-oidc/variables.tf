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

# NOTE: there is deliberately no default_branch variable.
#
# An earlier version conditioned the apply role on
# repo:owner/name:ref:refs/heads/main. That is correct only for a job with no
# `environment:` declared; once the job targets a GitHub environment the branch
# leaves the sub claim entirely. Keeping a branch variable here would imply a
# control this module no longer exercises. Branch restriction belongs on the
# GitHub environment's deployment rules.

variable "state_bucket_arn" {
  description = "ARN of the Terraform state bucket. Both roles need it; a plan writes the lock object."
  type        = string
}

variable "apply_environment" {
  description = <<-EOT
    GitHub environment the apply job targets.

    This name goes into the sub claim the apply role trusts, because declaring
    `environment:` on a job makes GitHub swap the ref-based sub for an
    environment-based one. Restrict which branches may deploy to it on the
    GitHub environment itself, not here.
  EOT
  type        = string
  default     = "dev"
}
