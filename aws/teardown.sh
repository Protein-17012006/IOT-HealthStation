#!/usr/bin/env bash
# =============================================================================
#  Tear down everything deploy.sh created (stops all AWS charges).
#  Run from the repo root:   bash aws/teardown.sh
# =============================================================================
set -euo pipefail

REGION="${AWS_REGION:-ap-southeast-1}"
ECR_STACK="health-station-ecr"
MAIN_STACK="health-station"
REPO_NAME="health-station-dashboard"

echo "==> Deleting main stack ($MAIN_STACK) -- this removes RDS, ECS, ALB, API GW, VPC"
aws cloudformation delete-stack --region "$REGION" --stack-name "$MAIN_STACK"
aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$MAIN_STACK"
echo "    main stack deleted"

echo "==> Emptying ECR repo images (so the ECR stack can delete)"
IMAGE_IDS="$(aws ecr list-images --region "$REGION" --repository-name "$REPO_NAME" \
  --query 'imageIds[*]' --output json 2>/dev/null || echo '[]')"
if [ "$IMAGE_IDS" != "[]" ] && [ -n "$IMAGE_IDS" ]; then
  aws ecr batch-delete-image --region "$REGION" --repository-name "$REPO_NAME" \
    --image-ids "$IMAGE_IDS" >/dev/null || true
fi

echo "==> Deleting ECR stack ($ECR_STACK)"
aws cloudformation delete-stack --region "$REGION" --stack-name "$ECR_STACK"
aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$ECR_STACK"

echo "Done. All resources removed."
