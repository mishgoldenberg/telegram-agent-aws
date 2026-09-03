variable "project" {
  description = "Project slug."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, prod)."
  type        = string
}

variable "lambda_invoke_arn" {
  description = "invoke_arn of the ingest Lambda."
  type        = string
}

variable "lambda_function_name" {
  description = "Name of that Lambda, for the invoke permission."
  type        = string
}

variable "webhook_path" {
  description = <<-EOT
    Path segment for the webhook route. Pass a high-entropy value so the URL is
    unguessable. This is obscurity layered on top of real authentication (the
    secret-token header), never instead of it.
  EOT
  type        = string
  sensitive   = true
}

variable "throttle_rate_limit" {
  description = "Sustained requests/second. One human needs a tiny fraction of this."
  type        = number
  default     = 2
}

variable "throttle_burst_limit" {
  description = "Bucket size for momentary spikes."
  type        = number
  default     = 5
}

variable "integration_timeout_ms" {
  description = "Give up before Telegram does, so a hang is a 504 rather than a retry storm."
  type        = number
  default     = 10000
}

variable "log_retention_days" {
  description = "Access log retention."
  type        = number
  default     = 7
}
