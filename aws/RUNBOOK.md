# AWS Runbook — turn the cloud backend ON / OFF

Operational checklist for the hybrid deployment (see the README "Cloud
deployment (AWS)" section for the architecture). Region: `ap-southeast-1`.

---

First, **stop the local processes** (they only feed the cloud; nothing to clean
up): press **Ctrl+C** in the WSL terminal (YOLO detector) and in the Windows
terminal (`edge/main.py`). Then pick ONE of the two options below.

### Option A — Pause (keep everything, don't delete)  ⬅️ recommended for "just turn it off"
Stops the compute bill (ECS + RDS) but **keeps the stack, the data, and the same
URLs** — so bringing it back is fast and nothing needs reconfiguring.
```bash
REGION=ap-southeast-1
# 1) scale the web service to zero tasks
aws ecs update-service --region $REGION --cluster health-station \
  --service health-station-web --desired-count 0 >/dev/null
# 2) stop the database (find its id, then stop it)
DBID=$(aws cloudformation describe-stack-resources --region $REGION \
  --stack-name health-station --logical-resource-id Database \
  --query "StackResources[0].PhysicalResourceId" --output text)
aws rds stop-db-instance --region $REGION --db-instance-identifier "$DBID"
```
> Leftover cost while paused ≈ **US$0.5/day** (the ALB can't be stopped, only
> deleted). RDS auto-starts after **7 days** — if you're pausing longer, re-run
> the stop command or use Option B. To resume, see "Turn everything ON → Resume".

### Option B — Full teardown (delete everything, ~$0/day)
```bash
bash aws/teardown.sh
```
> ⚠️ Deletes the RDS database (no snapshot) and the URLs. Fine for a finished
> demo — data regenerates and `deploy.sh` makes fresh URLs next time.

---

## 🟢 Turn everything ON again (later)

### Resume from a PAUSE (Option A) — fast, URLs unchanged
```bash
REGION=ap-southeast-1
DBID=$(aws cloudformation describe-stack-resources --region $REGION \
  --stack-name health-station --logical-resource-id Database \
  --query "StackResources[0].PhysicalResourceId" --output text)
aws rds start-db-instance --region $REGION --db-instance-identifier "$DBID"
# wait ~5 min until the DB is "available", then bring the web service back:
aws ecs update-service --region $REGION --cluster health-station \
  --service health-station-web --desired-count 1 >/dev/null
```
The AlbUrl / ApiGatewayUrl / RdsEndpoint and the login/token are all unchanged,
so just re-run the local edge server + detector (Steps 2–3) and reopen the site.
Fetch the current values any time with the `describe-stacks` command below.

If instead you did a **full teardown** (Option B), start from Step 1.

### Step 1 — Deploy the cloud (only after a full teardown)
Prereqs: AWS CLI logged in, **Docker Desktop running**, bash + curl.
```bash
bash aws/deploy.sh
```
Wait ~10–15 min (image build + RDS creation). At the end it prints the outputs.
Re-read them any time with:
```bash
aws cloudformation describe-stacks --region ap-southeast-1 \
  --stack-name health-station \
  --query "Stacks[0].Outputs[].{Key:OutputKey,Value:OutputValue}" --output table
```
You get these outputs (they change on every fresh deploy) — copy them:
- `AlbUrl`        — full dashboard (open this in the browser)
- `ApiGatewayUrl` — managed API URL (no live video through it)
- `RdsEndpoint`   — DB host for `main.py`
- `RdsSecretArn`  — Secrets Manager ARN for the DB password
- `DashSecretArn` — dashboard login (username/password)
- `IngestSecretArn` — device token for the detector

`deploy.sh` also **prints the dashboard login and the detector token** at the
end. Fetch them again any time:
```bash
aws secretsmanager get-secret-value --region ap-southeast-1 \
  --secret-id <DashSecretArn>   --query SecretString --output text   # {"username","password"}
aws secretsmanager get-secret-value --region ap-southeast-1 \
  --secret-id <IngestSecretArn> --query SecretString --output text   # {"token"}
```

### Fall-alert email (SNS)
On the first deploy, AWS SNS sends a **"Subscription Confirmation"** email to the
`AlertEmail` address (default `huyhoang17012006@gmail.com`). You MUST click
**Confirm subscription** once — until then no fall alerts are delivered. Change
the recipient with `ALERT_EMAIL=<addr> bash aws/deploy.sh`.

### Step 2 — Start the edge server on Windows (ESP32 → cloud over HTTP)
The DB is private, so main.py PUSHES readings to the cloud via HTTP (no direct
DB connection). PowerShell, from the repo root:
```powershell
$env:CLOUD_URL="<AlbUrl>"
$env:INGEST_TOKEN="<token>"    # from the deploy output / IngestSecretArn
$env:SIM=0
$env:SERIAL_PORT="COM7"        # your ESP32 port
python edge/main.py
```
(No ESP32 on hand? Use `$env:SIM=1` to stream fake sensor data instead.)

### Step 3 — Start the GPU detector in WSL (falls + video → cloud)
Needs BOTH the cloud URL and the ingest token (from the deploy output):
```bash
cd /mnt/c/Users/huyho/OneDrive/Desktop/IOT/edge
DASHBOARD_URL="<AlbUrl>" INGEST_TOKEN="<token>" \
  ./run_fall_detector.sh "http://admin:170106@<iphone-ip>:8081/video"
```
Confirm the log shows `report : <AlbUrl>/api/fall` (NOT `172.31.x.x`). Without
the token, the cloud rejects the POSTs with 403.

### Step 4 — Open the dashboard
Open **`<AlbUrl>`** in the browser (the `http://...elb.amazonaws.com` one) and
**log in** with the dashboard username/password. Use the ALB URL — not the API
Gateway URL — so the live annotated video and the SSE live updates work.

---

## Notes
- **No IP allow-listing needed.** The database is private; edge devices reach the
  cloud over HTTP with the ingest token, so a changing home IP (CGNAT) doesn't
  matter anymore.
- **Cost while ON:** ~US$1–2/day (ALB + RDS + Fargate).
- **Redeploy without teardown:** re-running `deploy.sh` updates the existing
  stacks in place (keeps the URLs and data). Teardown is only for stopping cost.
