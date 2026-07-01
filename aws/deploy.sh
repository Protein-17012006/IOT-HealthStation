#!/usr/bin/env bash
# =============================================================================
#  Deploy the Smart Patient Monitoring Station backend to AWS.
#
#  1. Create the ECR repo stack.
#  2. Build the dashboard image and push it to ECR.
#  3. Create the main stack (VPC + private RDS + ECS + ALB + API Gateway).
#  4. Print the outputs + the dashboard login and the device ingest token.
#
#  Requirements: aws cli (logged in), docker running, bash + curl.
#  Run from the repo root:   bash aws/deploy.sh
# =============================================================================
set -euo pipefail

REGION="${AWS_REGION:-ap-southeast-1}"
ECR_STACK="health-station-ecr"
MAIN_STACK="health-station"
REPO_NAME="health-station-dashboard"
# Unique tag per build so CloudFormation sees the TaskDefinition change and ECS
# actually rolls out the new image (a fixed ':latest' tag would NOT change the
# task def, so ECS would keep running the old image).
IMAGE_TAG="${IMAGE_TAG:-$(date +%Y%m%d-%H%M%S)}"

# repo root = parent of this script's dir, so paths work from anywhere
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> [1/4] ECR repository stack ($REGION)"
aws cloudformation deploy \
  --region "$REGION" \
  --stack-name "$ECR_STACK" \
  --template-file aws/cloudformation/ecr.yaml \
  --parameter-overrides RepoName="$REPO_NAME"

REPO_URI="$(aws cloudformation describe-stacks --region "$REGION" \
  --stack-name "$ECR_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='RepositoryUri'].OutputValue" \
  --output text)"
REGISTRY="${REPO_URI%/*}"
IMAGE_URI="${REPO_URI}:${IMAGE_TAG}"
echo "    repo: $IMAGE_URI"

echo "==> [2/4] Build + push image"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"
# linux/amd64 so the image runs on Fargate regardless of the build host arch
docker build --platform linux/amd64 -t "$IMAGE_URI" -f edge/Dockerfile edge
docker push "$IMAGE_URI"

echo "==> [3/4] Main stack (RDS takes ~5-10 min the first time)"
aws cloudformation deploy \
  --region "$REGION" \
  --stack-name "$MAIN_STACK" \
  --template-file aws/cloudformation/main.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides ImageUri="$IMAGE_URI" AlertEmail="${ALERT_EMAIL:-huyhoang17012006@gmail.com}"

echo "==> [4/4] Outputs"
aws cloudformation describe-stacks --region "$REGION" \
  --stack-name "$MAIN_STACK" \
  --query "Stacks[0].Outputs" --output table

# --- resolve the app credentials so you can log in / configure the detector ---
get_out() { aws cloudformation describe-stacks --region "$REGION" \
  --stack-name "$MAIN_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
DASH_ARN="$(get_out DashSecretArn)"
INGEST_ARN="$(get_out IngestSecretArn)"
DASH_JSON="$(aws secretsmanager get-secret-value --region "$REGION" \
  --secret-id "$DASH_ARN" --query SecretString --output text 2>/dev/null || echo '{}')"
INGEST_JSON="$(aws secretsmanager get-secret-value --region "$REGION" \
  --secret-id "$INGEST_ARN" --query SecretString --output text 2>/dev/null || echo '{}')"
# tiny JSON field extractor (no jq dependency)
jval() { sed -n 's/.*"'"$2"'":"\([^"]*\)".*/\1/p' <<<"$1"; }
DASH_U="$(jval "$DASH_JSON" username)"
DASH_P="$(jval "$DASH_JSON" password)"
INGEST_T="$(jval "$INGEST_JSON" token)"

echo
echo "==> App credentials (from Secrets Manager)"
echo "    Dashboard login : ${DASH_U:-admin} / ${DASH_P:-<see $DASH_ARN>}"
echo "    Detector token  : INGEST_TOKEN=${INGEST_T:-<see $INGEST_ARN>}"

cat <<EOF

Done. Next (RDS is private -- the edge devices talk to the cloud over HTTP):
  * Open the AlbUrl in a browser  -> log in with the Dashboard login above.
  * Point the local edge server at the cloud (pushes readings via HTTP):
      CLOUD_URL=<AlbUrl>  INGEST_TOKEN=<token above>  python edge/main.py
  * Point the local YOLO detector at the cloud (needs BOTH vars):
      DASHBOARD_URL=<AlbUrl>  INGEST_TOKEN=<token above>  ./run_fall_detector.sh "<camera-url>"
  * Tear everything down when the demo is over:  bash aws/teardown.sh
EOF
