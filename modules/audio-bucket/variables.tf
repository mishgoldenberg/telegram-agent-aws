variable "project" {
  description = "Project slug."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, prod)."
  type        = string
}

variable "name_suffix" {
  description = <<-EOT
    Suffix making the bucket name globally unique. Pass the account hash, not
    the account id — bucket names end up in committed config and public repos.
  EOT
  type        = string
}

variable "account_id" {
  description = "Account id, used as the source_account condition on the S3 invoke permission."
  type        = string
}

variable "expire_after_days" {
  description = <<-EOT
    Days before a voice note is deleted. This is a privacy control first and a
    cost control second: the audio is worthless after transcription.
  EOT
  type        = number
  default     = 7

  validation {
    condition     = var.expire_after_days >= 1 && var.expire_after_days <= 90
    error_message = "Keep voice notes for between 1 and 90 days; indefinite retention is not a valid choice here."
  }
}

variable "object_prefix" {
  description = "Key prefix that triggers transcription. Scopes the event to intended uploads only."
  type        = string
  default     = "voice/"
}

variable "notify_lambda_arn" {
  description = "ARN of the Lambda invoked on ObjectCreated."
  type        = string
}

variable "notify_lambda_name" {
  description = "Name of that Lambda, for the resource-policy permission."
  type        = string
}

variable "force_destroy" {
  description = <<-EOT
    Allow terraform destroy to delete a non-empty bucket. True in dev because
    the contents are transient by design; should be false in prod.
  EOT
  type        = bool
  default     = true
}
