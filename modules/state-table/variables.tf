variable "project" {
  description = "Project slug."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, prod)."
  type        = string
}

variable "point_in_time_recovery" {
  description = "Continuous backups. Priced per GB-month of table size, which is ~0 here."
  type        = bool
  default     = true
}
