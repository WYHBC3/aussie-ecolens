#!/usr/bin/env bash
set -euo pipefail

# ==========================================
# P2 Deployment Script - GSI dedup version
#
# Creates/updates:
# - S3 bucket and prefixes
# - DynamoDB a2_group92_files table
# - checksum_sha256-index GSI
# - Pillow Lambda layer
# - ffmpeg Lambda layer
# - P2 S3 upload Lambda
# - S3 uploads/ trigger
#
# No AWS credentials are stored in this file.
# ==========================================

REGION="${REGION:-us-east-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

P2_BUCKET="${P2_BUCKET:-a2-group92-p2-media-${ACCOUNT_ID}}"
LAMBDA_NAME="${LAMBDA_NAME:-s3-upload-trigger}"

FILES_TABLE="${FILES_TABLE:-a2_group92_files}"
CHECKSUM_INDEX="${CHECKSUM_INDEX:-checksum_sha256-index}"

PILLOW_LAYER_NAME="${PILLOW_LAYER_NAME:-p2-pillow-thumbnail-layer}"
FFMPEG_LAYER_NAME="${FFMPEG_LAYER_NAME:-p2-ffmpeg-frame-layer}"

RUNTIME="python3.12"
ARCHITECTURE="x86_64"
TIMEOUT=300
MEMORY_SIZE=1024
EPHEMERAL_STORAGE=1024

BUILD_DIR=".build_p2"
LAMBDA_SRC="backend/file-pipeline/lambda_s3_upload_trigger.py"

# Set USE_EXISTING_BUCKET=true when the AWS account does not allow CreateBucket.
USE_EXISTING_BUCKET="${USE_EXISTING_BUCKET:-false}"

# Use Python Launcher on Windows Git Bash.
# python3 may point to old Python 3.7, so prefer py -3.14 or py -3.12.
if command -v py >/dev/null 2>&1; then
  if py -3.14 --version >/dev/null 2>&1; then
    PYTHON_CMD="py -3.14"
  elif py -3.12 --version >/dev/null 2>&1; then
    PYTHON_CMD="py -3.12"
  else
    PYTHON_CMD="py -3"
  fi
else
  PYTHON_CMD="python3"
fi

echo "=========================================="
echo "P2 deployment started"
echo "Region: $REGION"
echo "Account: $ACCOUNT_ID"
echo "Bucket: $P2_BUCKET"
echo "Lambda: $LAMBDA_NAME"
echo "Files table: $FILES_TABLE"
echo "Checksum index: $CHECKSUM_INDEX"
echo "Use existing bucket: $USE_EXISTING_BUCKET"
echo "Python command: $PYTHON_CMD"
$PYTHON_CMD --version
echo "=========================================="

if [ ! -f "$LAMBDA_SRC" ]; then
  echo "ERROR: Lambda source file not found: $LAMBDA_SRC"
  exit 1
fi

# ------------------------------------------
# Helper: create zip without requiring system zip command
# ------------------------------------------
create_zip_from_dir() {
  local source_dir="$1"
  local output_zip="$2"

  rm -f "$output_zip"

  ZIP_SOURCE="$source_dir" ZIP_OUTPUT="$output_zip" $PYTHON_CMD - <<'PY'
import os
import zipfile

source = os.environ["ZIP_SOURCE"]
output = os.environ["ZIP_OUTPUT"]

with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, _, files in os.walk(source):
        for file_name in files:
            full_path = os.path.join(root, file_name)
            arc_name = os.path.relpath(full_path, source)
            zf.write(full_path, arc_name)

print(f"Created zip: {output}")
PY
}

# ------------------------------------------
# Resolve Lambda execution role
# ------------------------------------------
get_lab_role_arn() {
  aws iam get-role --role-name LabRole --query 'Role.Arn' --output text 2>/dev/null || \
  aws iam get-role --role-name labRole --query 'Role.Arn' --output text 2>/dev/null || \
  true
}

ROLE_ARN="${ROLE_ARN:-$(get_lab_role_arn)}"

if [ -z "$ROLE_ARN" ]; then
  echo "Could not query LabRole/labRole directly. Falling back to default LabRole ARN."
  ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/LabRole"
fi

echo "Using Lambda role: $ROLE_ARN"

mkdir -p "$BUILD_DIR"

# ------------------------------------------
# 1. Create or reuse S3 bucket and prefixes
# ------------------------------------------
echo "Creating or checking S3 bucket..."

if [ "$USE_EXISTING_BUCKET" = "true" ]; then
  echo "Using existing bucket without creating it: $P2_BUCKET"
else
  if aws s3api head-bucket --bucket "$P2_BUCKET" 2>/dev/null; then
    echo "Bucket already exists: $P2_BUCKET"
  else
    if [ "$REGION" = "us-east-1" ]; then
      aws s3api create-bucket \
        --bucket "$P2_BUCKET" \
        --region "$REGION"
    else
      aws s3api create-bucket \
        --bucket "$P2_BUCKET" \
        --region "$REGION" \
        --create-bucket-configuration LocationConstraint="$REGION"
    fi

    echo "Bucket created: $P2_BUCKET"
  fi
fi

echo "Creating S3 prefixes..."
aws s3api put-object --bucket "$P2_BUCKET" --key "uploads/" >/dev/null
aws s3api put-object --bucket "$P2_BUCKET" --key "thumbnails/" >/dev/null
aws s3api put-object --bucket "$P2_BUCKET" --key "video-frames/" >/dev/null
aws s3api put-object --bucket "$P2_BUCKET" --key "temp-query/" >/dev/null

# ------------------------------------------
# 2. Create DynamoDB table with GSI
# ------------------------------------------
wait_for_checksum_index() {
  echo "Waiting for GSI $CHECKSUM_INDEX to become ACTIVE..."

  while true; do
    INDEX_STATUS="$(aws dynamodb describe-table \
      --table-name "$FILES_TABLE" \
      --region "$REGION" \
      --query "Table.GlobalSecondaryIndexes[?IndexName=='$CHECKSUM_INDEX'].IndexStatus | [0]" \
      --output text 2>/dev/null || true)"

    echo "Current GSI status: $INDEX_STATUS"

    if [ "$INDEX_STATUS" = "ACTIVE" ]; then
      echo "GSI is ACTIVE: $CHECKSUM_INDEX"
      break
    fi

    sleep 10
  done
}

ensure_checksum_gsi() {
  INDEX_COUNT="$(aws dynamodb describe-table \
    --table-name "$FILES_TABLE" \
    --region "$REGION" \
    --query "length(Table.GlobalSecondaryIndexes[?IndexName=='$CHECKSUM_INDEX'])" \
    --output text 2>/dev/null || echo "0")"

  if [ "$INDEX_COUNT" = "1" ]; then
    echo "GSI already exists: $CHECKSUM_INDEX"
    wait_for_checksum_index
  else
    echo "Creating GSI: $CHECKSUM_INDEX"

    aws dynamodb update-table \
      --table-name "$FILES_TABLE" \
      --attribute-definitions AttributeName=checksum_sha256,AttributeType=S \
      --global-secondary-index-updates "[
        {
          \"Create\": {
            \"IndexName\": \"$CHECKSUM_INDEX\",
            \"KeySchema\": [
              {\"AttributeName\": \"checksum_sha256\", \"KeyType\": \"HASH\"}
            ],
            \"Projection\": {\"ProjectionType\": \"ALL\"}
          }
        }
      ]" \
      --region "$REGION" >/dev/null

    wait_for_checksum_index
  fi
}

echo "Creating/checking DynamoDB table: $FILES_TABLE"

if aws dynamodb describe-table --table-name "$FILES_TABLE" --region "$REGION" >/dev/null 2>&1; then
  echo "Table already exists: $FILES_TABLE"
  ensure_checksum_gsi
else
  echo "Creating table with checksum GSI..."

  aws dynamodb create-table \
    --table-name "$FILES_TABLE" \
    --attribute-definitions \
      AttributeName=file_id,AttributeType=S \
      AttributeName=checksum_sha256,AttributeType=S \
    --key-schema AttributeName=file_id,KeyType=HASH \
    --global-secondary-indexes "[
      {
        \"IndexName\": \"$CHECKSUM_INDEX\",
        \"KeySchema\": [
          {\"AttributeName\": \"checksum_sha256\", \"KeyType\": \"HASH\"}
        ],
        \"Projection\": {\"ProjectionType\": \"ALL\"}
      }
    ]" \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" >/dev/null

  aws dynamodb wait table-exists \
    --table-name "$FILES_TABLE" \
    --region "$REGION"

  echo "Table created: $FILES_TABLE"
  wait_for_checksum_index
fi

# ------------------------------------------
# 3. Build Pillow layer
# ------------------------------------------
echo "Building Pillow layer..."

rm -rf "$BUILD_DIR/pillow-layer" "$BUILD_DIR/pillow-layer.zip"
mkdir -p "$BUILD_DIR/pillow-layer/python"

$PYTHON_CMD -m pip install --upgrade pip >/dev/null

PIP_USER=false $PYTHON_CMD -m pip install \
  --no-user \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.12 \
  --abi cp312 \
  --only-binary=:all: \
  pillow \
  -t "$BUILD_DIR/pillow-layer/python" >/dev/null

create_zip_from_dir "$BUILD_DIR/pillow-layer" "$BUILD_DIR/pillow-layer.zip"

PILLOW_LAYER_ARN="$(aws lambda publish-layer-version \
  --layer-name "$PILLOW_LAYER_NAME" \
  --zip-file "fileb://$BUILD_DIR/pillow-layer.zip" \
  --compatible-runtimes "$RUNTIME" \
  --compatible-architectures "$ARCHITECTURE" \
  --region "$REGION" \
  --query 'LayerVersionArn' \
  --output text)"

echo "Pillow layer published: $PILLOW_LAYER_ARN"

# ------------------------------------------
# 4. Build ffmpeg layer
# ------------------------------------------
echo "Building ffmpeg layer..."

rm -rf "$BUILD_DIR/ffmpeg-layer" "$BUILD_DIR/ffmpeg-layer.zip" "$BUILD_DIR/ffmpeg.tar.xz" "$BUILD_DIR"/ffmpeg-*-static
mkdir -p "$BUILD_DIR/ffmpeg-layer/bin"

curl -L https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz \
  -o "$BUILD_DIR/ffmpeg.tar.xz"

tar -xf "$BUILD_DIR/ffmpeg.tar.xz" -C "$BUILD_DIR"

cp "$BUILD_DIR"/ffmpeg-*-static/ffmpeg "$BUILD_DIR/ffmpeg-layer/bin/"
chmod +x "$BUILD_DIR/ffmpeg-layer/bin/ffmpeg"

create_zip_from_dir "$BUILD_DIR/ffmpeg-layer" "$BUILD_DIR/ffmpeg-layer.zip"

FFMPEG_LAYER_ARN="$(aws lambda publish-layer-version \
  --layer-name "$FFMPEG_LAYER_NAME" \
  --zip-file "fileb://$BUILD_DIR/ffmpeg-layer.zip" \
  --compatible-runtimes "$RUNTIME" \
  --compatible-architectures "$ARCHITECTURE" \
  --region "$REGION" \
  --query 'LayerVersionArn' \
  --output text)"

echo "ffmpeg layer published: $FFMPEG_LAYER_ARN"

# ------------------------------------------
# 5. Package Lambda function
# ------------------------------------------
echo "Packaging Lambda function..."

rm -rf "$BUILD_DIR/lambda-package" "$BUILD_DIR/lambda-package.zip"
mkdir -p "$BUILD_DIR/lambda-package"

cp "$LAMBDA_SRC" "$BUILD_DIR/lambda-package/lambda_s3_upload_trigger.py"

create_zip_from_dir "$BUILD_DIR/lambda-package" "$BUILD_DIR/lambda-package.zip"

# ------------------------------------------
# 6. Prepare Lambda environment variables
# ------------------------------------------
if [ -n "${P3_LAMBDA_NAME:-}" ]; then
  cat > "$BUILD_DIR/lambda-env.json" <<EOF
{
  "Variables": {
    "FILES_TABLE": "$FILES_TABLE",
    "CHECKSUM_INDEX": "$CHECKSUM_INDEX",
    "P3_LAMBDA_NAME": "$P3_LAMBDA_NAME",
    "ENABLE_SECONDARY_STORAGE": "${ENABLE_SECONDARY_STORAGE:-false}",
    "SECONDARY_PROVIDER": "${SECONDARY_PROVIDER:-gcp}",
    "GCS_BUCKET": "${GCS_BUCKET:-}",
    "GCP_COPY_ENDPOINT": "${GCP_COPY_ENDPOINT:-}",
    "GCP_COPY_SECRET": "${GCP_COPY_SECRET:-}"
  }
}
EOF
else
  cat > "$BUILD_DIR/lambda-env.json" <<EOF
{
  "Variables": {
    "FILES_TABLE": "$FILES_TABLE",
    "CHECKSUM_INDEX": "$CHECKSUM_INDEX",
    "ENABLE_SECONDARY_STORAGE": "${ENABLE_SECONDARY_STORAGE:-false}",
    "SECONDARY_PROVIDER": "${SECONDARY_PROVIDER:-gcp}",
    "GCS_BUCKET": "${GCS_BUCKET:-}",
    "GCP_COPY_ENDPOINT": "${GCP_COPY_ENDPOINT:-}",
    "GCP_COPY_SECRET": "${GCP_COPY_SECRET:-}"
  }
}
EOF
fi

# ------------------------------------------
# 7. Create or update Lambda
# ------------------------------------------
echo "Creating/updating Lambda function..."

if aws lambda get-function --function-name "$LAMBDA_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "Lambda exists. Updating code and configuration..."

  aws lambda update-function-code \
    --function-name "$LAMBDA_NAME" \
    --zip-file "fileb://$BUILD_DIR/lambda-package.zip" \
    --region "$REGION" >/dev/null

  aws lambda wait function-updated \
    --function-name "$LAMBDA_NAME" \
    --region "$REGION"

  aws lambda update-function-configuration \
    --function-name "$LAMBDA_NAME" \
    --runtime "$RUNTIME" \
    --handler "lambda_s3_upload_trigger.lambda_handler" \
    --role "$ROLE_ARN" \
    --timeout "$TIMEOUT" \
    --memory-size "$MEMORY_SIZE" \
    --ephemeral-storage "Size=$EPHEMERAL_STORAGE" \
    --layers "$PILLOW_LAYER_ARN" "$FFMPEG_LAYER_ARN" \
    --environment "file://$BUILD_DIR/lambda-env.json" \
    --region "$REGION" >/dev/null

  aws lambda wait function-updated \
    --function-name "$LAMBDA_NAME" \
    --region "$REGION"
else
  echo "Lambda does not exist. Creating new function..."

  aws lambda create-function \
    --function-name "$LAMBDA_NAME" \
    --runtime "$RUNTIME" \
    --handler "lambda_s3_upload_trigger.lambda_handler" \
    --role "$ROLE_ARN" \
    --zip-file "fileb://$BUILD_DIR/lambda-package.zip" \
    --timeout "$TIMEOUT" \
    --memory-size "$MEMORY_SIZE" \
    --ephemeral-storage "Size=$EPHEMERAL_STORAGE" \
    --layers "$PILLOW_LAYER_ARN" "$FFMPEG_LAYER_ARN" \
    --environment "file://$BUILD_DIR/lambda-env.json" \
    --region "$REGION" >/dev/null
fi

aws lambda wait function-active \
  --function-name "$LAMBDA_NAME" \
  --region "$REGION"

LAMBDA_ARN="$(aws lambda get-function \
  --function-name "$LAMBDA_NAME" \
  --region "$REGION" \
  --query 'Configuration.FunctionArn' \
  --output text)"

echo "Lambda ARN: $LAMBDA_ARN"

# ------------------------------------------
# 8. Allow S3 to invoke Lambda
# ------------------------------------------
echo "Adding Lambda permission for S3 trigger..."

aws lambda add-permission \
  --function-name "$LAMBDA_NAME" \
  --statement-id "AllowS3InvokeFromP2Bucket" \
  --action "lambda:InvokeFunction" \
  --principal "s3.amazonaws.com" \
  --source-arn "arn:aws:s3:::$P2_BUCKET" \
  --source-account "$ACCOUNT_ID" \
  --region "$REGION" >/dev/null 2>&1 || true

sleep 5

# ------------------------------------------
# 9. Configure S3 trigger
# ------------------------------------------
echo "Configuring S3 event notification for uploads/ prefix..."

cat > "$BUILD_DIR/s3-notification.json" <<EOF
{
  "LambdaFunctionConfigurations": [
    {
      "Id": "P2UploadsTrigger",
      "LambdaFunctionArn": "$LAMBDA_ARN",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {
        "Key": {
          "FilterRules": [
            {
              "Name": "prefix",
              "Value": "uploads/"
            }
          ]
        }
      }
    }
  ]
}
EOF

aws s3api put-bucket-notification-configuration \
  --bucket "$P2_BUCKET" \
  --notification-configuration "file://$BUILD_DIR/s3-notification.json" \
  --region "$REGION"

echo "=========================================="
echo "P2 deployment completed successfully"
echo "Bucket: $P2_BUCKET"
echo "Lambda: $LAMBDA_NAME"
echo "DynamoDB table: $FILES_TABLE"
echo "GSI: $CHECKSUM_INDEX"
echo "Layers:"
echo "- $PILLOW_LAYER_ARN"
echo "- $FFMPEG_LAYER_ARN"
echo "=========================================="
