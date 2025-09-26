import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone


ENABLE_LOGGING = os.environ.get("ENABLE_LOGGING", "false").lower() == "true"


def log(*args, **kwargs):
    if ENABLE_LOGGING:
        print(*args, **kwargs)


def get_env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def build_user_summary(user_identity: dict) -> tuple[str, dict]:
    """
    Returns a short user string and a dict of extra user fields for Slack.
    """
    if not isinstance(user_identity, dict):
        return ("unknown", {})

    utype = user_identity.get("type")
    account_id = user_identity.get("accountId")
    principal = user_identity.get("principalId")
    arn = user_identity.get("arn") or ""
    username = user_identity.get("userName")

    extras = {"Account": account_id or "-", "Principal": principal or "-"}

    if utype == "IAMUser":
        short = username or principal or "iam-user"
        extras["UserType"] = "IAMUser"
        return short, extras

    if utype == "AssumedRole":
        session_name = arn.split("/")[-1] if "/" in arn else (username or principal or "assumed-role")
        issuer = (
            user_identity.get("sessionContext", {})
            .get("sessionIssuer", {})
            .get("arn")
        ) or "-"
        extras["UserType"] = "AssumedRole"
        extras["RoleIssuer"] = issuer
        return session_name, extras

    if utype == "Root":
        extras["UserType"] = "Root"
        return "Root", extras

    extras["UserType"] = utype or "Unknown"
    return username or principal or arn or "unknown", extras


def to_iso8601(ts: str | None) -> str:
    if not ts:
        return "-"
    try:
        # CloudTrail eventTime is already ISO8601 (e.g., 2024-01-01T12:34:56Z)
        # We re-parse to ensure consistent formatting.
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    except Exception:
        return ts


def build_slack_payload(event: dict) -> dict:
    detail = event.get("detail", {})
    event_name = detail.get("eventName", "UnknownEvent")
    region = detail.get("awsRegion", "-")
    event_time = to_iso8601(detail.get("eventTime"))
    source_ip = detail.get("sourceIPAddress", "-")
    user_agent = detail.get("userAgent", "-")

    user_str, user_fields = build_user_summary(detail.get("userIdentity", {}))

    req = detail.get("requestParameters", {}) or {}
    resp = detail.get("responseElements", {}) or {}

    # SSM specifics
    target = req.get("target") or req.get("Target") or "-"  # EC2 instance-id if present
    reason = req.get("reason") or req.get("Reason") or "-"
    session_id = (
        resp.get("sessionId")
        or resp.get("SessionId")
        or (resp.get("StartSessionResponse", {}).get("SessionId"))
        or "-"
    )

    emoji = ":large_blue_circle:" if event_name == "StartSession" else ":white_check_mark:" if event_name == "TerminateSession" else ":information_source:"
    title = f"{emoji} SSM {event_name}"

    # Base text fallback for clients that don't render blocks
    text_lines = [
        f"SSM {event_name}",
        f"User: {user_str}",
        f"Account: {user_fields.get('Account', '-')}",
        f"Target: {target}",
        f"SessionId: {session_id}",
        f"Region: {region}",
        f"Source IP: {source_ip}",
        f"Time: {event_time}",
    ]
    if reason and reason != "-":
        text_lines.append(f"Reason: {reason}")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": title},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*User*\n{user_str}"},
                {"type": "mrkdwn", "text": f"*Account*\n{user_fields.get('Account', '-')}"},
                {"type": "mrkdwn", "text": f"*Target*\n{target}"},
                {"type": "mrkdwn", "text": f"*Session ID*\n{session_id}"},
                {"type": "mrkdwn", "text": f"*Region*\n{region}"},
                {"type": "mrkdwn", "text": f"*Source IP*\n{source_ip}"},
            ],
        },
    ]

    if reason and reason != "-":
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Reason*\n{reason}"}}
        )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Time: {event_time}"},
                {"type": "mrkdwn", "text": f"UserAgent: {user_agent}"},
            ],
        }
    )

    payload: dict = {
        "text": "\n".join(text_lines),  # fallback text
        "blocks": blocks,
        "unfurl_links": False,
        "unfurl_media": False,
        "username": "SSM Alerts",
        "icon_emoji": ":lock:",
    }

    slack_channel = get_env("SLACK_CHANNEL", "").strip()
    if slack_channel:
        payload["channel"] = slack_channel

    return payload


def send_to_slack(payload: dict) -> tuple[int, str]:
    webhook = get_env("SLACK_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError("SLACK_WEBHOOK_URL is not set")

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.getcode()
            resp_body = resp.read().decode("utf-8", errors="replace")
            return status, resp_body
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        return e.code, err
    except urllib.error.URLError as e:
        return 599, str(e)


def lambda_handler(event, context):
    log("Received event:", json.dumps(event))
    try:
        payload = build_slack_payload(event)
        status, resp = send_to_slack(payload)
        log(f"Slack response: {status} {resp}")

        if status >= 400:
            return {"statusCode": status, "body": json.dumps({"error": resp})}

        return {"statusCode": 200, "body": json.dumps({"ok": True})}
    except Exception as e:
        log("Error:", repr(e))
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
