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
    """Build a richer Slack Block Kit payload with emojis, risk flags and quick-glance formatting."""
    detail = event.get("detail", {})
    event_name = detail.get("eventName", "UnknownEvent")
    region = detail.get("awsRegion", "-")
    event_time = to_iso8601(detail.get("eventTime"))
    source_ip = detail.get("sourceIPAddress", "-")
    user_agent = detail.get("userAgent", "-")
    event_id = detail.get("eventID") or detail.get("eventId") or "-"

    user_str, user_fields = build_user_summary(detail.get("userIdentity", {}))
    user_type = user_fields.get("UserType", "-")

    req = detail.get("requestParameters", {}) or {}
    resp = detail.get("responseElements", {}) or {}
    target = req.get("target") or req.get("Target") or "-"
    doc_name = req.get("documentName") or req.get("DocumentName") or "-"
    reason = req.get("reason") or req.get("Reason") or "-"
    session_id = (
        resp.get("sessionId")
        or resp.get("SessionId")
        or (resp.get("StartSessionResponse", {}).get("SessionId"))
        or "-"
    )

    # Primary emoji & accent
    primary_emoji = ":large_blue_circle:" if event_name == "StartSession" else ":information_source:"

    # Risk flags
    risk_flags = []
    if user_type == "Root":
        risk_flags.append(":rotating_light: *ROOT ACCOUNT* :rotating_light:")
    if user_type == "AssumedRole" and any(x in user_str.lower() for x in ["admin", "prod", "power"]):
        risk_flags.append(":warning: privileged role?")
    if source_ip not in ("-", "127.0.0.1") and not source_ip.startswith("10.") and not source_ip.startswith("192.168.") and not source_ip.startswith("172.16."):
        # simplistic external vs RFC1918 check
        risk_flags.append(":globe_with_meridians: external IP")

    # Console helper link (best-effort)
    console_link = None
    if event_id != "-" and region != "-":
        console_link = f"https://{region}.console.aws.amazon.com/cloudtrail/home?region={region}#/events/{event_id}"

    # Fallback text
    fallback = f"{event_name} {user_str} -> {target} ({region}) session={session_id} doc={doc_name} ip={source_ip}"
    if reason and reason != "-":
        fallback += f" reason={reason}"

    header_text = f"{primary_emoji} SSM {event_name}"

    # Build main section with a richer single markdown block for better mobile rendering
    summary_lines = [
        f"*User:* {user_str}  |  *Acct:* {user_fields.get('Account', '-')}",
        f"*Target:* `{target}`  |  *Session:* `{session_id}`",
        f"*Doc:* `{doc_name}`  |  *Region:* {region}",
        f"*IP:* {source_ip}",
    ]
    if reason and reason != "-":
        summary_lines.append(f"*Reason:* _{reason}_")
    if risk_flags:
        summary_lines.append("\n".join(risk_flags))

    icon_url = os.environ.get("ICON_URL", "").strip()

    section_block = {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(summary_lines)},
    }
    if icon_url:
        section_block["accessory"] = {"type": "image", "image_url": icon_url, "alt_text": "icon"}

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}},
        section_block,
    ]

    # Divider for visual separation
    blocks.append({"type": "divider"})

    context_elems = [
        {"type": "mrkdwn", "text": f"*Time:* {event_time}"},
        {"type": "mrkdwn", "text": f"*UserType:* {user_type}"},
        {"type": "mrkdwn", "text": f"UA: {user_agent[:60]}"},
    ]
    if console_link:
        context_elems.append({"type": "mrkdwn", "text": f"<" + console_link + "|CloudTrail Event>"})

    blocks.append({"type": "context", "elements": context_elems})

    payload: dict = {
        "text": fallback,
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


def handler(event, context):
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
