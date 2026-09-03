variable "project" {
  description = "Project slug; also the cost-allocation tag value the budget filters on."
  type        = string
}

variable "limit_usd" {
  description = "Monthly budget ceiling in USD."
  type        = string
  default     = "5"
}

variable "any_spend_threshold_usd" {
  description = <<-EOT
    Threshold for the 'am I spending at all' budget. Deliberately just above
    zero rather than zero: AWS rounds sub-cent amounts, and a literal 0 budget
    notifies on every trivial rounding artefact.
  EOT
  type        = string
  default     = "1"
}

variable "alert_emails" {
  description = "Addresses that receive budget notifications. No confirmation step, unlike SNS."
  type        = list(string)

  validation {
    condition     = length(var.alert_emails) > 0
    error_message = "At least one alert email is required — a budget nobody receives is not a guardrail."
  }
}

variable "scope_to_project_tag" {
  description = <<-EOT
    Filter the monthly budget to resources tagged Project=<project>.

    Defaults to false because cost allocation tags must be activated in the
    Billing console and take up to 24h to backfill; a tag-filtered budget
    reports $0 until then, which looks like success and is actually blindness.
    Flip to true once the tag shows as Active.
  EOT
  type        = bool
  default     = false
}
