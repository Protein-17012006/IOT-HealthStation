# Fall-Alert Email (Amazon SNS) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Email a caregiver address whenever the AI detects a fall, published from the cloud dashboard's `/api/fall` handler via Amazon SNS.

**Architecture:** A small, unit-tested `notify.py` module publishes a fall message to an SNS topic (created in CloudFormation) using the ECS task role. `api_fall()` calls it after logging the event. A 5-minute in-process cooldown prevents duplicate emails; the feature is inert when `FALL_ALERT_TOPIC_ARN` is unset, so local/SIM runs are unchanged.

**Tech Stack:** Python 3.12, Flask, boto3 (SNS), AWS CloudFormation, ECS Fargate, Amazon SNS.

## Global Constraints

- **Branch:** all commits go to the existing feature branch `feat/fall-alert-email`. Do NOT push to `main` or open the PR until Task 5.
- **No Claude attribution** in any commit message (no `Co-Authored-By` trailer, no generated-by footer).
- **Feature is opt-in:** every code path is a no-op when the env var `FALL_ALERT_TOPIC_ARN` is empty (mirrors the auth vars in `app.py`). Local/SIM behaviour must not change.
- **SNS subject is ASCII only** — no emoji in the `Subject` line (SNS rejects non-ASCII subjects).
- **Single gunicorn worker** (`-w 1`, already set in `edge/Dockerfile`) makes the module-level cooldown state correct — do not add more workers.
- **boto3 ships only in the cloud image.** Import it lazily inside the publish path so the module (and its tests) import without boto3 installed.
- **Tests** follow the repo's existing style: plain `test_*()` functions with bare `assert` and a `__main__` runner (see `edge/test_fall_detector.py`). Run with `python <file>.py`.

---

### Task 1: `notify.py` — cooldown + message + gated SNS publish

**Files:**
- Create: `edge/webapp/notify.py`
- Test: `edge/webapp/test_notify.py`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces:
  - `should_send(now: float, last_ts: float, cooldown: float) -> bool`
  - `build_message(confidence: float, source: str, now: float, patient_name=None, dashboard_url="") -> (subject: str, body: str)`
  - `notify_fall(confidence, source, now=None, client=None) -> bool` — returns `True` iff an email was published; never raises.
  - Module globals (overridable in tests): `TOPIC_ARN`, `COOLDOWN`, `PUBLIC_URL`, `_last_email_ts`.

- [ ] **Step 1: Write the failing tests**

Create `edge/webapp/test_notify.py`:

```python
"""
Unit tests for the fall-alert email logic (edge/webapp/notify.py).

No AWS, no network, no boto3: the SNS client is a fake that records calls and
the cooldown clock is passed in explicitly. Run:  python test_notify.py
"""
import notify


class _FakeSns:
    def __init__(self):
        self.calls = []

    def publish(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "fake"}


def _reset(topic="arn:aws:sns:ap-southeast-1:0:health-station-fall", cooldown=300):
    notify.TOPIC_ARN = topic
    notify.COOLDOWN = cooldown
    notify.PUBLIC_URL = "http://alb.example"
    notify._last_email_ts = 0.0


def test_should_send_true_after_cooldown():
    assert notify.should_send(now=1000.0, last_ts=0.0, cooldown=300) is True


def test_should_send_false_within_cooldown():
    assert notify.should_send(now=100.0, last_ts=0.0, cooldown=300) is False


def test_build_message_has_confidence_source_and_link():
    subject, body = notify.build_message(0.87, "YOLOv8s", now=0.0,
                                         dashboard_url="http://alb.example")
    assert subject == "FALL DETECTED - Patient Monitoring Station"
    assert subject.isascii()
    assert "0.87" in body
    assert "YOLOv8s" in body
    assert "http://alb.example" in body


def test_notify_fall_disabled_when_no_topic():
    _reset(topic="")
    fake = _FakeSns()
    assert notify.notify_fall(0.9, "YOLO", now=1000.0, client=fake) is False
    assert fake.calls == []


def test_notify_fall_publishes_first_time():
    _reset()
    fake = _FakeSns()
    assert notify.notify_fall(0.9, "YOLO", now=1000.0, client=fake) is True
    assert len(fake.calls) == 1
    assert fake.calls[0]["TopicArn"] == notify.TOPIC_ARN
    assert "FALL DETECTED" in fake.calls[0]["Subject"]


def test_notify_fall_suppressed_within_cooldown():
    _reset()
    fake = _FakeSns()
    assert notify.notify_fall(0.9, "YOLO", now=1000.0, client=fake) is True
    assert notify.notify_fall(0.9, "YOLO", now=1060.0, client=fake) is False
    assert len(fake.calls) == 1


def test_notify_fall_sends_again_after_cooldown():
    _reset()
    fake = _FakeSns()
    assert notify.notify_fall(0.9, "YOLO", now=1000.0, client=fake) is True
    assert notify.notify_fall(0.9, "YOLO", now=1400.0, client=fake) is True
    assert len(fake.calls) == 2


def test_notify_fall_swallows_publish_error():
    _reset()

    class _Boom:
        def publish(self, **kw):
            raise RuntimeError("sns down")

    assert notify.notify_fall(0.9, "YOLO", now=1000.0, client=_Boom()) is False
    # a failed publish must NOT consume the cooldown slot
    assert notify._last_email_ts == 0.0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print("PASS", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} tests passed")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd edge/webapp && python test_notify.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'notify'`.

- [ ] **Step 3: Write the minimal implementation**

Create `edge/webapp/notify.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd edge/webapp && python test_notify.py`
Expected: PASS — `8/8 tests passed`.

- [ ] **Step 5: Commit**

```bash
git add edge/webapp/notify.py edge/webapp/test_notify.py
git commit -m "Add fall-alert email notifier (SNS) with cooldown"
```

---

### Task 2: Wire `notify_fall` into the `/api/fall` handler

**Files:**
- Modify: `edge/webapp/app.py` (imports near line 33-35; `api_fall()` at lines 265-277)
- Test: `edge/webapp/test_api_fall.py`

**Interfaces:**
- Consumes: `notify.notify_fall(confidence, source)` from Task 1.
- Produces: no new public symbols; `api_fall()` now fires the notifier after logging.

- [ ] **Step 1: Write the failing test**

Create `edge/webapp/test_api_fall.py`:

```python
"""
Wiring test: POST /api/fall logs the event AND fires the email notifier.
Uses Flask's test client with db.insert_event + notify.notify_fall stubbed
(no DB, no AWS). Requires Flask + PyMySQL installed (same as running the
dashboard locally). Run:  python test_api_fall.py
"""
import app as webapp
import db
import notify


def test_api_fall_logs_event_and_calls_notify():
    events = []
    calls = []
    orig_insert, orig_notify = db.insert_event, notify.notify_fall
    db.insert_event = lambda *a, **k: events.append(a)
    notify.notify_fall = lambda confidence, source, **k: calls.append((confidence, source))
    try:
        client = webapp.app.test_client()
        resp = client.post("/api/fall",
                           json={"confidence": 0.83, "source": "YOLOv8s"})
        assert resp.status_code == 200
        assert len(events) == 1                 # fall event still logged
        assert len(calls) == 1                  # notifier fired exactly once
        assert abs(calls[0][0] - 0.83) < 1e-6
        assert calls[0][1] == "YOLOv8s"
    finally:
        db.insert_event, notify.notify_fall = orig_insert, orig_notify


if __name__ == "__main__":
    test_api_fall_logs_event_and_calls_notify()
    print("PASS test_api_fall_logs_event_and_calls_notify")
    print("\n1/1 tests passed")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd edge/webapp && python test_api_fall.py`
Expected: FAIL — `AttributeError: module 'notify' has no attribute 'notify_fall'` if Task 1 is skipped, otherwise `assert len(calls) == 1` fails (notifier not wired yet).

- [ ] **Step 3: Add the import**

In `edge/webapp/app.py`, after the sibling/parent imports (the line `import rules  # noqa: E402`, ~line 35), add:

```python
import notify  # noqa: E402  (sibling module in webapp/)
```

- [ ] **Step 4: Call the notifier in `api_fall()`**

In `edge/webapp/app.py`, change `api_fall()` (lines 265-277) so the body reads:

```python
@app.route("/api/fall", methods=["POST"])
def api_fall():
    """Receive a fall alert from the GPU detector (edge/fall_detector_yolo.py,
    running in WSL) and log it so the dashboard banner lights up."""
    data = request.get_json(force=True) or {}
    try:
        conf = float(data.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        conf = 0.0
    source = str(data.get("source", "AI"))[:32]
    db.insert_event("fall", "critical",
                    f"FALL DETECTED by {source} (confidence {conf:.2f})")
    notify.notify_fall(conf, source)   # best-effort email alert (no-op if unset)
    return jsonify({"ok": True})
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd edge/webapp && python test_api_fall.py`
Expected: PASS — `1/1 tests passed`.

- [ ] **Step 6: Re-run Task 1 tests to confirm no regression**

Run: `cd edge/webapp && python test_notify.py`
Expected: PASS — `8/8 tests passed`.

- [ ] **Step 7: Commit**

```bash
git add edge/webapp/app.py edge/webapp/test_api_fall.py
git commit -m "Fire fall-alert email from /api/fall handler"
```

---

### Task 3: Cloud enablement — boto3, SNS topic, task role, env, docs

**Files:**
- Modify: `edge/webapp/requirements-web.txt`
- Modify: `aws/cloudformation/main.yaml`
- Modify: `aws/deploy.sh:56`
- Modify: `aws/RUNBOOK.md` and `README.md` (subscription-confirmation note)

**Interfaces:**
- Consumes: env vars read by `notify.py` (`FALL_ALERT_TOPIC_ARN`, `FALL_ALERT_COOLDOWN`, `PUBLIC_URL`).
- Produces: SNS topic `FallAlertTopic`, an email subscription to `AlertEmail`, a `TaskRole` with `sns:Publish`, and stack output `FallAlertTopicArn`.

- [ ] **Step 1: Add boto3 to the cloud image requirements**

In `edge/webapp/requirements-web.txt`, append:

```
boto3>=1.34
```

- [ ] **Step 2: Add the `AlertEmail` parameter**

In `aws/cloudformation/main.yaml`, in the `Parameters:` block after `DbInstanceClass` (lines 22-24), add:

```yaml
  AlertEmail:
    Type: String
    Default: huyhoang17012006@gmail.com
    Description: Email address that receives fall alerts (SNS subscription).
```

- [ ] **Step 3: Add the SNS topic + email subscription**

In `aws/cloudformation/main.yaml`, after the `IngestTokenSecret` resource (ends ~line 182, before the `# ---- ECS` comment), add:

```yaml
  # ---- Fall-alert email (SNS) ----------------------------------------------
  FallAlertTopic:
    Type: AWS::SNS::Topic
    Properties:
      TopicName: health-station-fall-alerts
      DisplayName: Health Station Fall Alert

  FallAlertSubscription:
    Type: AWS::SNS::Subscription
    Properties:
      TopicArn: !Ref FallAlertTopic
      Protocol: email
      Endpoint: !Ref AlertEmail
```

- [ ] **Step 4: Add the ECS task role (grants sns:Publish)**

In `aws/cloudformation/main.yaml`, after the `ExecutionRole` resource (ends ~line 218, before `Cluster:`), add:

```yaml
  TaskRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: health-station-ecs-task
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal: { Service: ecs-tasks.amazonaws.com }
            Action: sts:AssumeRole
      Policies:
        - PolicyName: publish-fall-alerts
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Effect: Allow
                Action: sns:Publish
                Resource: !Ref FallAlertTopic
```

- [ ] **Step 5: Attach the task role + inject the env vars**

In `aws/cloudformation/main.yaml` `TaskDefinition`, add `TaskRoleArn` right after `ExecutionRoleArn` (line 233):

```yaml
      ExecutionRoleArn: !GetAtt ExecutionRole.Arn
      TaskRoleArn: !GetAtt TaskRole.Arn
```

Then in the same container's `Environment:` list, after the `DASH_USER` entry (line 246), add:

```yaml
            - { Name: FALL_ALERT_TOPIC_ARN, Value: !Ref FallAlertTopic }
            - { Name: FALL_ALERT_COOLDOWN, Value: "300" }
            - { Name: PUBLIC_URL, Value: !Sub "http://${LoadBalancer.DNSName}" }
```

- [ ] **Step 6: Output the topic ARN**

In `aws/cloudformation/main.yaml` `Outputs:`, after `IngestSecretArn` (line 384), add:

```yaml
  FallAlertTopicArn:
    Description: SNS topic that emails fall alerts (confirm the email subscription!).
    Value: !Ref FallAlertTopic
```

- [ ] **Step 7: Pass the email through deploy.sh**

In `aws/deploy.sh`, change the main-stack parameter line (line 56) from:

```bash
  --parameter-overrides ImageUri="$IMAGE_URI"
```

to:

```bash
  --parameter-overrides ImageUri="$IMAGE_URI" AlertEmail="${ALERT_EMAIL:-huyhoang17012006@gmail.com}"
```

- [ ] **Step 8: Document the subscription-confirmation step**

In `aws/RUNBOOK.md`, add a short note (place it near the deploy section):

```markdown
### Fall-alert email (SNS)
On the first deploy, AWS SNS sends a **"Subscription Confirmation"** email to the
`AlertEmail` address (default `huyhoang17012006@gmail.com`). You MUST click
**Confirm subscription** once — until then no fall alerts are delivered. Change
the recipient with `ALERT_EMAIL=<addr> bash aws/deploy.sh`.
```

In `README.md`, under the AWS **Security**/deployment section, add one line:

```markdown
- **Fall-alert email.** On a fall, the dashboard publishes to an SNS topic that
  emails the caregiver address (`AlertEmail`). Confirm the SNS subscription email
  once after the first deploy.
```

- [ ] **Step 9: Validate the CloudFormation template**

Run: `aws cloudformation validate-template --region ap-southeast-1 --template-body file://aws/cloudformation/main.yaml`
Expected: prints the parameter list including `AlertEmail`, exit 0, no errors. (Free, read-only; needs the AWS CLI logged in.)

- [ ] **Step 10: Commit**

```bash
git add edge/webapp/requirements-web.txt aws/cloudformation/main.yaml aws/deploy.sh aws/RUNBOOK.md README.md
git commit -m "Provision SNS fall-alert email (topic, task role, env, docs)"
```

---

### Task 4: Deploy + end-to-end verification (user-driven — touches live AWS + email)

**Files:** none (operational).

**Interfaces:** consumes the deployed stack outputs `AlbUrl`, `IngestSecretArn`, `FallAlertTopicArn`.

- [ ] **Step 1: Deploy**

Run (Docker Desktop must be running): `bash aws/deploy.sh`
Expected: builds+pushes the image, updates the `health-station` stack, prints outputs including `FallAlertTopicArn` and the dashboard login + detector token.

- [ ] **Step 2: Confirm the SNS subscription**

Open the inbox of `huyhoang17012006@gmail.com`, find the AWS "Subscription Confirmation" email, and click **Confirm subscription**. (One time only.)

- [ ] **Step 3: Trigger a synthetic fall**

Using the `AlbUrl` and detector token from the deploy output:

```bash
curl -X POST "<AlbUrl>/api/fall" \
  -H "X-Ingest-Token: <token>" \
  -H "Content-Type: application/json" \
  -d '{"confidence":0.9,"source":"manual-test"}'
```
Expected: `{"ok": true}`.

- [ ] **Step 4: Confirm the email arrives**

Expected: within ~1 minute, an email with subject `FALL DETECTED - Patient Monitoring Station` arrives at `huyhoang17012006@gmail.com`, showing the time, confidence `0.90`, source `manual-test`, and the dashboard link.

- [ ] **Step 5: Confirm the cooldown**

Immediately re-run the same `curl`. Expected: `{"ok": true}` again but **no** second email (suppressed by the 5-minute cooldown). Check the ECS logs if needed: `aws logs tail /ecs/health-station --region ap-southeast-1 --since 5m`.

---

### Task 5: Ship — push branch and open PR (user merges on GitHub)

**Files:** none (git/GitHub).

- [ ] **Step 1: Push the feature branch**

```bash
git push -u origin feat/fall-alert-email
```

- [ ] **Step 2: Open the PR (no Claude footer)**

```bash
gh pr create --base main --head feat/fall-alert-email \
  --title "Fall-alert email notification via Amazon SNS" \
  --body "Emails a caregiver address on AI fall detection: new SNS topic + email subscription, an ECS task role with sns:Publish, and a best-effort, cooldown-gated notify.py fired from /api/fall. Feature is off when FALL_ALERT_TOPIC_ARN is unset (local/SIM unchanged). See docs/superpowers/specs/2026-07-01-fall-alert-email-design.md."
```

- [ ] **Step 3: Hand off**

Tell the user the PR is up for them to review and merge on GitHub (per repo workflow, Claude does not self-merge).

---

## Self-Review

**Spec coverage:**
- Service = SNS → Tasks 3 (topic/subscription) + 1 (`sns.publish`). ✓
- Runs on ECS, task-role auth → Task 3 Step 4-5 (TaskRole + TaskRoleArn). ✓
- 5-minute cooldown → Task 1 (`should_send`, tests) + env `FALL_ALERT_COOLDOWN=300`. ✓
- Off when unset (local/SIM) → Task 1 (`if not TOPIC_ARN`) + tests. ✓
- Message content (time/confidence/source/link) → Task 1 `build_message` + test. ✓
- Best-effort (never breaks `/api/fall`) → Task 1 try/except + swallow test. ✓
- ASCII subject → Task 1 subject + `isascii()` assert. ✓
- Subscription-confirmation note → Task 3 Step 8. ✓
- Cost/deploy notes → covered operationally in Task 4. ✓
- Patient name = out of scope (optional) → intentionally omitted; `build_message` still accepts `patient_name` for a future wire-up. ✓

**Placeholder scan:** no TBD/TODO; all code and commands are concrete. ✓

**Type consistency:** `notify_fall(confidence, source, now=None, client=None)`, `should_send(now, last_ts, cooldown)`, and `build_message(...)` names/signatures match between `notify.py`, the tests, and the `app.py` call site. Env var names (`FALL_ALERT_TOPIC_ARN`, `FALL_ALERT_COOLDOWN`, `PUBLIC_URL`) match between `notify.py` and the CloudFormation `Environment` block. ✓
