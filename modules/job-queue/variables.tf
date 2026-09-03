variable "project" {
  description = "Project slug."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, prod)."
  type        = string
}

variable "visibility_timeout_seconds" {
  description = <<-EOT
    How long a received message stays invisible before SQS assumes the consumer
    died and redelivers it. Must exceed worst-case processing time (Whisper
    transcription plus an LLM turn) or slow jobs get answered twice.
  EOT
  type        = number
  default     = 300

  validation {
    condition     = var.visibility_timeout_seconds >= 30 && var.visibility_timeout_seconds <= 43200
    error_message = "SQS allows 0-43200s; below 30s is too tight for local inference."
  }
}

variable "message_retention_seconds" {
  description = <<-EOT
    How long an unprocessed message survives. Short on purpose: a conversational
    reply that arrives six hours late is worse than no reply.
  EOT
  type        = number
  default     = 3600
}

variable "max_receive_count" {
  description = "Delivery attempts before a message is moved to the DLQ."
  type        = number
  default     = 3
}
