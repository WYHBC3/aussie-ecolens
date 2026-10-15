#!/usr/bin/env bash

set -euo pipefail

EXPECTED_ACCOUNT_ID="909774767032"
REGION="${AWS_REGION:-us-east-1}"

FILES_TABLE="a2_group92_files"
TAG_INDEX_TABLE="a2_group92_tag_index"
ECR_REPO="a2-group92-tagging-lambda"

echo "Checking AWS account and region..."

CURRENT_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "Current AWS account: $CURRENT_ACCOUNT_ID"
echo "Expected AWS account: $EXPECTED_ACCOUNT_ID"
echo "Region: $REGION"

if [ "$CURRENT_ACCOUNT_ID" != "$EXPECTED_ACCOUNT_ID" ]; then
  echo "ERROR: Wrong AWS account."
  echo "This script must be run in the Cognito AWS account: $EXPECTED_ACCOUNT_ID"
  echo "Current account is: $CURRENT_ACCOUNT_ID"
  exit 1
fi

echo ""
echo "Creating or verifying DynamoDB table: $FILES_TABLE"

if aws dynamodb describe-table --table-name "$FILES_TABLE" --region "$REGION" >/dev/null 2>&1; then
  echo "Table already exists: $FILES_TABLE"
else
  aws dynamodb create-table \
    --table-name "$FILES_TABLE" \
    --attribute-definitions AttributeName=file_id,AttributeType=S \
    --key-schema AttributeName=file_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION"

  aws dynamodb wait table-exists \
    --table-name "$FILES_TABLE" \
    --region "$REGION"

  echo "Created table: $FILES_TABLE"
fi

echo ""
echo "Creating or verifying DynamoDB table: $TAG_INDEX_TABLE"

if aws dynamodb describe-table --table-name "$TAG_INDEX_TABLE" --region "$REGION" >/dev/null 2>&1; then
  echo "Table already exists: $TAG_INDEX_TABLE"
else
  aws dynamodb create-table \
    --table-name "$TAG_INDEX_TABLE" \
    --attribute-definitions \
      AttributeName=tag,AttributeType=S \
      AttributeName=file_id,AttributeType=S \
    --key-schema \
      AttributeName=tag,KeyType=HASH \
      AttributeName=file_id,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION"

  aws dynamodb wait table-exists \
    --table-name "$TAG_INDEX_TABLE" \
    --region "$REGION"

  echo "Created table: $TAG_INDEX_TABLE"
fi

echo ""
echo "Creating or verifying ECR repository: $ECR_REPO"

if aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$REGION" >/dev/null 2>&1; then
  echo "ECR repository already exists: $ECR_REPO"
else
  aws ecr create-repository \
    --repository-name "$ECR_REPO" \
    --region "$REGION" >/dev/null

  echo "Created ECR repository: $ECR_REPO"
fi

FILES_TABLE_ARN=$(aws dynamodb describe-table \
  --table-name "$FILES_TABLE" \
  --region "$REGION" \
  --query "Table.TableArn" \
  --output text)

TAG_INDEX_TABLE_ARN=$(aws dynamodb describe-table \
  --table-name "$TAG_INDEX_TABLE" \
  --region "$REGION" \
  --query "Table.TableArn" \
  --output text)

ECR_URI=$(aws ecr describe-repositories \
  --repository-names "$ECR_REPO" \
  --region "$REGION" \
  --query "repositories[0].repositoryUri" \
  --output text)

echo ""
echo "Person3 AWS resources are ready."
echo "AWS Account ID: $CURRENT_ACCOUNT_ID"
echo "Region: $REGION"
echo "Files table name: $FILES_TABLE"
echo "Files table ARN: $FILES_TABLE_ARN"
echo "Tag index table name: $TAG_INDEX_TABLE"
echo "Tag index table ARN: $TAG_INDEX_TABLE_ARN"
echo "ECR repository name: $ECR_REPO"
echo "ECR URI: $ECR_URI"
