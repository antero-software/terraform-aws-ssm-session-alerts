# terraform-aws-ssm-session-alerts
Terraform module to capture all AWS SSM Session Manager login events via CloudTrail + EventBridge and send real-time alerts to Slack. Includes optional logging for auditing and compliance.

## What this module does

- Creates an EventBridge rule that listens to SSM StartSession and TerminateSession API events coming from CloudTrail.
- Deploys a Python AWS Lambda function that formats the event and posts a rich message to Slack via an incoming webhook.
- Optionally enables enhanced logging to CloudWatch Logs (enabled by default, configurable via variable).

## Architecture

CloudTrail → EventBridge (rule: ssm StartSession/TerminateSession) → Lambda (Python) → Slack webhook

Resources created by this module:
- CloudWatch Logs log group for the Lambda
- IAM role and basic execution policy for the Lambda
- Lambda function built from `src/lambda_function.py`
- EventBridge rule + target + Lambda invoke permission

## Requirements

- Terraform >= 1.0
- AWS provider >= 5.0
- A Slack Incoming Webhook URL

## Usage

Minimal example:

```hcl
module "ssm_session_alerts" {
	source = "./" # or the VCS source

	name_prefix       = "ssm-alerts"TF_
	slack_webhook_url = var.slack_webhook_url
	# Optional
	slack_channel     = "#security-alerts"
	enable_logging    = true
	log_retention_days = 30
	tags = {
		Project = "ssm-session-alerts"
	}
}
```

Set your Slack webhook URL securely (for example via TF var file or environment variable):

```sh
export TF_VAR_slack_webhook_url="https://hooks.slack.com/services/XXXXX/XXXXX/XXXXX"
```

Then plan/apply:

```sh
terraform init
terraform plan
terraform apply
```

## Variables

- `name_prefix` (string, default: `"ssm-alerts"`)
	Prefix for resource names.

- `slack_webhook_url` (string, sensitive, required)
	Slack webhook URL for sending alerts.

- `slack_channel` (string, default: empty)
	Slack channel to post to. If omitted, the webhook’s default channel is used.

- `enable_logging` (bool, default: `true`)
	Enable enhanced logging in Lambda (prints event and responses to CloudWatch).

- `log_retention_days` (number, default: `30`)
	CloudWatch Logs retention for the Lambda log group.

- `tags` (map(string), default: `{}`)
	Tags applied to created resources.

## Outputs

- `lambda_function_name` – Name of the Lambda function
- `lambda_function_arn` – ARN of the Lambda function
- `eventbridge_rule_name` – Name of the EventBridge rule
- `eventbridge_rule_arn` – ARN of the EventBridge rule
- `log_group_name` – CloudWatch log group name for the Lambda
- `iam_role_arn` – ARN of the Lambda IAM role

## Lambda implementation

The Lambda code lives in `src/lambda_function.py` and:
- Builds a Slack Block Kit message with details: user, account, region, source IP, target (instance), session ID, time, and reason (if provided).
- Supports optional channel override via `SLACK_CHANNEL` env var.
- Uses only the standard library (urllib) for HTTP; no external dependencies.

Environment variables set by this module:
- `SLACK_WEBHOOK_URL` – provided via variable
- `SLACK_CHANNEL` – optional override
- `ENABLE_LOGGING` – `true|false`

## Event pattern details

The module matches CloudTrail events with:

```json
{
	"source": ["aws.ssm"],
	"detail-type": ["AWS API Call via CloudTrail"],
	"detail": {
		"eventSource": ["ssm.amazonaws.com"],
		"eventName": ["StartSession", "TerminateSession"]
	}
}
```

## Notes & troubleshooting

- Ensure CloudTrail is enabled for your account/region so that SSM API calls appear as events.
- If Slack messages do not arrive, check the Lambda’s CloudWatch logs and verify the webhook URL and (optional) channel.
- Some SSM responses may not include a `sessionId` depending on the event; the message will still be sent with available context.

## License

See `LICENSE` for details.
