# Variables for SSM Session Manager Alerts module

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
  default     = "ssm-alerts"
}

variable "slack_webhook_url" {
  description = "Slack webhook URL for sending alerts"
  type        = string
  sensitive   = true
}

variable "slack_channel" {
  description = "Slack channel for alerts (optional, webhook URL channel will be used if not specified)"
  type        = string
  default     = ""
}

variable "enable_logging" {
  description = "Enable enhanced logging for auditing and compliance"
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch logs retention period in days"
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
