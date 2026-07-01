# Fall-Alert Email Notification — Design Spec

**Date:** 2026-07-01
**Topic:** Send an email to the medical/caregiver address when the AI detects a fall.
**Deliverable:** an Amazon SNS email notification fired from the cloud dashboard's
`/api/fall` handler, provisioned via CloudFormation.

## Goal
When the AI fall detector reports a fall (`POST /api/fall`), the system must email a
caregiver/medical address so a human is alerted even when nobody is watching the
dashboard. Demo recipient: `huyhoang17012006@gmail.com`.

## Decisions (from brainstorming)
- **Service:** **Amazon SNS** (Simple Notification Service) — a topic with an email
  subscription. Chosen over SES for simplicity: it declares fully in CloudFormation,
  needs no sender/recipient verification workflow in code, and is free at this scale.
  Trade-off accepted: SNS emails are plain-text, come from a generic AWS sender with an
  unsubscribe footer, and cannot carry attachments.
- **Where it runs:** the **AWS ECS (cloud) dashboard**. The email is published from the
  `api_fall()` handler running in the Fargate task, using the **ECS task role** for
  `sns:Publish`. No AWS credentials are needed on the local machine.
- **Anti-spam:** a **~5-minute cooldown** (default 300 s) — one email per fall episode;
  repeated `/api/fall` POSTs within the window are suppressed.

## Architecture
```
YOLO detector --POST /api/fall--> api_fall() [ECS Fargate, -w 1]
                                      |-- db.insert_event("fall","critical")   (existing)
                                      '-- notify_fall() -- boto3 sns.publish --> FallAlertTopic --> caregiver email
                                          (cooldown-gated, best-effort)
```

## Components

### 1. Infrastructure — `aws/cloudformation/main.yaml`
- **Parameter** `AlertEmail` (String, default `huyhoang17012006@gmail.com`) — change the
  recipient without touching code.
- **`FallAlertTopic`** (`AWS::SNS::Topic`) with an **`AWS::SNS::Subscription`**
  (protocol `email`, endpoint `!Ref AlertEmail`).
- **IAM:** add `sns:Publish` **scoped to `FallAlertTopic` only** to the existing ECS
  task-role policy (least privilege, matching the existing per-secret grants).
- **Container env:** inject `FALL_ALERT_TOPIC_ARN = !Ref FallAlertTopic`
  (and optional `FALL_ALERT_COOLDOWN=300`) into the ECS task definition.
- **Output** the topic ARN for reference.
- **Subscription confirmation (operational note):** on stack create, SNS emails a
  *"Subscription Confirmation"* to `AlertEmail`; the recipient MUST click
  **Confirm subscription** once before any alert is delivered. Document in `aws/RUNBOOK.md`.

### 2. Notification module — `edge/webapp/notify.py` (new)
A small, self-contained module so `app.py` stays focused and the logic is unit-testable.
- `notify_fall(confidence, source, ts, patient_name=None)` — builds the message, applies
  the cooldown, and calls SNS `publish`.
- **Gated on config:** if `FALL_ALERT_TOPIC_ARN` is empty/unset, do nothing (so local/SIM
  runs are unchanged — mirrors how auth auto-disables when its env vars are empty).
- **Cooldown:** module-level `_last_email_ts`. Correct because the Fargate container runs
  `gunicorn -w 1` (single worker — the same in-process-state constraint that `_ai_frame`
  relies on). The cooldown decision is factored into a **pure** helper
  `should_send(now, last_ts, cooldown)` for testing.
- **Best-effort:** wrap `publish` in `try/except`; on failure log a warning and return —
  never raise, so the `/api/fall` response and the dashboard banner are unaffected.

### 3. Wiring — `edge/webapp/app.py`
- In `api_fall()`, after the existing `db.insert_event(...)`, call
  `notify_fall(conf, source, ts=now)`. One added line plus the import.

## Email content (plain text)
- **Subject:** `FALL DETECTED - Patient Monitoring Station` (ASCII only — SNS rejects
  non-ASCII subjects, so no emoji in the subject line).
- **Body:** timestamp, confidence, detection source, and a link to open the dashboard
  (ALB URL). Optional: the current patient's name from the most recent RFID check-in, only
  if a `db` helper makes it cheap to fetch — otherwise omitted (no scope creep).

## Testing
- Unit tests for `notify.py` with a **mocked SNS client** (no real AWS call):
  - `should_send` returns `False` inside the cooldown window, `True` after it.
  - the built subject/body contain the confidence and source.
  - when `FALL_ALERT_TOPIC_ARN` is unset, `publish` is never called.
- Follows the repo's existing pure-function/unit-test style (`edge/test_fall_detector.py`).

## Deployment & cost
- Redeploy with `bash aws/deploy.sh` (updates the `health-station` stack). Adding an SNS
  topic, an env var and an IAM statement is a **light update** — it does **not** replace RDS.
- **Cost:** effectively free (first 1,000 email notifications/month free; negligible after).

## Out of scope (YAGNI)
- SES / HTML emails / image attachments.
- SMS or push notifications (listed as future work in the report).
- Per-recipient management UI; the recipient is a CloudFormation parameter.
