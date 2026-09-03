variable "project" {
  description = "Short project slug; prefixes every resource name."
  type        = string
  default     = "tg-agent"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,20}$", var.project))
    error_message = "Must be 3-20 chars: lowercase letters, digits, hyphens (S3 bucket naming rules)."
  }
}

variable "region" {
  description = <<-EOT
    AWS region for the state backend.

    eu-central-1 (Frankfurt) over il-central-1 (Tel Aviv): both carry every
    service this build needs; Tel Aviv is ~1.7% dearer on API Gateway
    ($1.22 vs $1.20 per million requests); and the ~40ms latency advantage is
    noise next to multi-second local LLM inference. Frankfurt also has broader
    service coverage, which matters when newer regions lag on new services.
  EOT
  type        = string
  default     = "eu-central-1"
}

variable "owner" {
  description = "Value for the Owner cost-allocation tag."
  type        = string
  default     = "mishgoldenberg"
}
