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

variable "lambda_memory_size" {
  description = "Memory size (MB) for the Lambda function. CPU is proportionally allocated based on memory. Minimum is 128."
  type        = number
  default     = 128
  validation {
    condition     = var.lambda_memory_size >= 128 && var.lambda_memory_size <= 10240
    error_message = "lambda_memory_size must be between 128 and 10240 MB."
  }
}
