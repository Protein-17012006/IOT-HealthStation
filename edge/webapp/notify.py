"""
Fall-alert email notification (Amazon SNS).

When the AI detector reports a fall (POST /api/fall), the dashboard publishes a
short message to an SNS topic; SNS emails the subscribed caregiver address. This
runs in the ECS Fargate task, using the task role for sns:Publish.

Config (all via environment; the whole feature is OFF when the topic ARN is
empty, so local / SIM runs are unchanged -- same convention as the auth vars in
app.py):
  FALL_ALERT_TOPIC_ARN   SNS topic to publish to (required to enable emails)
  FALL_ALERT_COOLDOWN    seconds to suppress repeat emails (default 300 = 5 min)
  PUBLIC_URL             dashboard URL placed in the email body (optional)

Publishing is best-effort: any SNS / boto3 error is logged and swallowed so the
/api/fall response and the dashboard banner are never affected.
"""
import logging
import os
import threading
import time

TOPIC_ARN = os.environ.get("FALL_ALERT_TOPIC_ARN", "")
try:
    COOLDOWN = float(os.environ.get("FALL_ALERT_COOLDOWN", "300"))
except ValueError:
    COOLDOWN = 300.0
PUBLIC_URL = os.environ.get("PUBLIC_URL", "")

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_last_email_ts = 0.0


def should_send(now, last_ts, cooldown):
    """True if enough time has passed since the last email (cooldown gate)."""
    return (now - last_ts) >= cooldown


def build_message(confidence, source, now, patient_name=None, dashboard_url=""):
    """Build the (subject, body) for a fall alert. Pure -- no AWS, no clock."""
    when = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(now))
    subject = "FALL DETECTED - Patient Monitoring Station"  # ASCII only (SNS req)
    lines = [
        "A fall was detected by the patient monitoring station.",
        "",
        f"Time       : {when}",
        f"Confidence : {confidence:.2f}",
        f"Detected by: {source}",
    ]
    if patient_name:
        lines.append(f"Patient    : {patient_name}")
    if dashboard_url:
        lines += ["", f"Open the dashboard: {dashboard_url}"]
    lines += ["", "-- Automated alert. Please check on the patient."]
    return subject, "\n".join(lines)


def notify_fall(confidence, source, now=None, client=None):
    """Publish a fall-alert email via SNS, respecting the cooldown.

    Returns True iff an email was published; False if the feature is disabled,
    still in cooldown, or publishing failed. Never raises.
    """
    if not TOPIC_ARN:
        return False                      # feature disabled (e.g. local / SIM)
    if now is None:
        now = time.time()
    global _last_email_ts
    with _lock:
        if not should_send(now, _last_email_ts, COOLDOWN):
            return False
        subject, body = build_message(confidence, source, now,
                                      dashboard_url=PUBLIC_URL)
        try:
            if client is None:
                import boto3            # lazy: only the cloud image ships boto3
                client = boto3.client("sns")
            client.publish(TopicArn=TOPIC_ARN, Subject=subject, Message=body)
        except Exception as exc:          # best-effort: never break /api/fall
            _log.warning("fall-alert email failed: %s", exc)
            return False
        _last_email_ts = now              # only consume the slot on success
        return True
