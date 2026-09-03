variable "project" {
  description = "Project slug."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, prod)."
  type        = string
}

variable "alert_emails" {
  description = "Recipients. Each must click the SNS confirmation email or receives nothing."
  type        = list(string)
}

variable "queue_name" {
  description = "Work queue name (metric dimension, not ARN)."
  type        = string
}

variable "dlq_name" {
  description = "Dead-letter queue name (metric dimension)."
  type        = string
}

variable "queue_age_threshold_seconds" {
  description = <<-EOT
    How long a job may wait before the worker is presumed dead.

    Tune to how the machine actually behaves. This PC never sleeps
    (STANDBYIDLE = 0 on AC and DC), so a few minutes of backlog is genuinely
    abnormal. On a laptop that sleeps nightly this would need to be hours, or
    the alarm becomes noise and gets ignored — which is worse than no alarm.
  EOT
  type        = number
  default     = 300
}

variable "max_receive_count" {
  description = "Mirrors the queue's redrive policy; used only in the alarm description."
  type        = number
  default     = 3
}

variable "lambda_function_names" {
  description = "Functions that each get their own error alarm."
  type        = list(string)
}

variable "ingest_function_name" {
  description = "The internet-facing function, which additionally gets a throttle alarm."
  type        = string
}
