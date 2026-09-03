variable "project" {
  description = "Project slug."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, prod)."
  type        = string
}

variable "name" {
  description = "Short function name; combined with project and environment."
  type        = string
}

variable "source_dir" {
  description = "Directory zipped as the deployment package. Dependency-free stdlib + boto3 only."
  type        = string
}

variable "handler" {
  description = "Entry point, module.function."
  type        = string
  default     = "handler.handler"
}

variable "runtime" {
  description = "Lambda runtime."
  type        = string
  default     = "python3.13"
}

variable "memory_mb" {
  description = <<-EOT
    Memory allocation. CPU scales proportionally, so more memory can be CHEAPER
    for compute-bound work by finishing sooner. These functions are I/O bound
    (HTTP to Telegram, PutItem, SendMessage), so the floor is fine.
  EOT
  type        = number
  default     = 256
}

variable "timeout_seconds" {
  description = <<-EOT
    Hard ceiling on execution. Deliberately short: the ingest path must
    acknowledge Telegram quickly, and a Lambda hanging on a slow dependency
    should fail fast rather than burn GB-seconds.
  EOT
  type        = number
  default     = 15
}

variable "reserved_concurrency" {
  description = <<-EOT
    Maximum simultaneous executions. Caps the blast radius of a flood against
    a public endpoint. -1 leaves the setting unmanaged.

    Note that AWS rejects any reservation that would drop the account's
    UnreservedConcurrentExecutions below 10. On a new account whose total limit
    IS 10, no reservation is possible and this must be -1 — see the comment at
    the call site in envs/dev.
  EOT
  type        = number
  default     = 5
}

variable "log_retention_days" {
  description = "CloudWatch log retention. Never leave this unset — the default is forever."
  type        = number
  default     = 7
}

variable "environment_variables" {
  description = "Environment variables. Never put secrets here — they are visible in the console."
  type        = map(string)
  default     = {}
}

variable "policy_statements" {
  description = <<-EOT
    Least-privilege IAM statements for this function, as a list of objects with
    Effect/Action/Resource. Every entry must name concrete ARNs; no wildcards.
  EOT
  type        = list(any)
  default     = []
}
