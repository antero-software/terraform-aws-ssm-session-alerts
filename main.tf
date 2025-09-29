# terraform-aws-ssm-session-alerts
# Main Terraform configuration for SSM Session Manager alerts

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4.0"
    }
  }
}

# Data sources for current identity and region
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# Locals
locals {
  # Lambda function name
  lambda_function_name = "${var.name_prefix}-ssm-session-alerts"
}

# CloudWatch Log Group for Lambda logs
resource "aws_cloudwatch_log_group" "ssm_alerts_lambda" {
  name              = "/aws/lambda/${local.lambda_function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# EventBridge rule to capture SSM StartSession API calls (via CloudTrail)
resource "aws_cloudwatch_event_rule" "ssm_session_events" {
  name        = "${var.name_prefix}-ssm-session-events"
  description = "Capture SSM Session Manager login events"

  event_pattern = jsonencode({
    source      = ["aws.ssm"]
    detail-type = ["AWS API Call via CloudTrail"]
    detail = {
      eventSource = ["ssm.amazonaws.com"]
      eventName   = ["StartSession"]
    }
  })

  tags = var.tags
}

# EventBridge target to invoke the Lambda
resource "aws_cloudwatch_event_target" "lambda_target" {
  rule       = aws_cloudwatch_event_rule.ssm_session_events.name
  target_id  = "SSMSessionAlertsLambdaTarget"
  arn        = aws_lambda_function.ssm_alerts.arn

  depends_on = [aws_lambda_permission.allow_eventbridge]
}

# Allow EventBridge to invoke the Lambda
resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ssm_alerts.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ssm_session_events.arn
}

# Lambda function (Python)
# Lambda function (Python) - use the manually created ZIP
resource "aws_lambda_function" "ssm_alerts" {
  # IMPORTANT: point to your manual ZIP inside the module
  filename         = "${path.module}/src/ssm-alerts-ssm-session-alerts.zip"
  # Ensure updates are detected when you re-zip
  source_code_hash = filebase64sha256("${path.module}/src/ssm-alerts-ssm-session-alerts.zip")

  function_name    = local.lambda_function_name
  role             = aws_iam_role.lambda_role.arn
  handler          = "lambda_function.lambda_handler"  # file is lambda_function.py in ZIP root
  runtime          = "python3.12"
  timeout          = 30
  memory_size      = var.lambda_memory_size

  environment {
    variables = {
      SLACK_WEBHOOK_URL = var.slack_webhook_url
      SLACK_CHANNEL     = var.slack_channel
      ENABLE_LOGGING    = var.enable_logging ? "true" : "false"
      ICON_URL          = var.icon_url
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_logs,
    aws_cloudwatch_log_group.ssm_alerts_lambda,
  ]

  tags = var.tags
}

# IAM role for the Lambda
resource "aws_iam_role" "lambda_role" {
  name = "${var.name_prefix}-ssm-alerts-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
      },
    ]
  })

  tags = var.tags
}

# Basic logging permissions for the Lambda
resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Optional extra CloudWatch Logs permissions when verbose logging is enabled
resource "aws_iam_role_policy" "lambda_additional_permissions" {
  count = var.enable_logging ? 1 : 0
  name  = "${var.name_prefix}-ssm-alerts-additional-permissions"
  role  = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
      }
    ]
  })
}
