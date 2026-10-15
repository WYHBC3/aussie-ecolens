#!/usr/bin/env bash
set -euo pipefail

# ==========================================
# P2 Storage Delete Lambda Deployment
#
# Creates/updates:
# - p2-storage-delete Lambda
#
# The Lambda deletes:
# - AWS S3 original files
# - AWS S3 thumbnails
# - AWS S3 extracted video frames
# - GCS secondary objects through the Cloud Run copy/delete bridge
# - DynamoDB file record
# - DynamoDB tag index entries
# ==========================================

REGION="${REGION:-us-east-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

DELETE_LAMBDA_NAME="${DELETE_LAMBDA_NAME:-p2-storage-delete}"
FILES_TABLE="${FILES_TABLE:-a2_group92_files}"
TAG_INDEX_TABLE="${TAG_INDEX_TABLE:-a2_group92_tag_index}"

RUNTIME="python3.12"
TIMEOUT=180
MEMORY_SIZE=512

BUILD_DIR=".build_p2_delete"
LAMBDA_SRC="backend/file-pipeline/lambda_delete_storage.py"

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
echo "P2 delete deployment started"
echo "Region: $REGION"
echo "Account: $ACCOUNT_ID"
echo "Lambda: $DELETE_LAMBDA_NAME"
echo "Files table: $FILES_TABLE"
echo "Tag index table: $TAG_INDEX_TABLE"
echo "Python command: $PYTHON_CMD"
$PYTHON_CMD --version
echo "=========================================="

if [ ! -f "$LAMBDA_SRC" ]; then
  echo "ERROR: Lambda source file not found: $LAMBDA_SRC"
  exit 1
fi

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

echo "Packaging delete Lambda..."
rm -rf "$BUILD_DIR/lambda-package" "$BUILD_DIR/lambda-package.zip"
mkdir -p "$BUILD_DIR/lambda-package"
cp "$LAMBDA_SRC" "$BUILD_DIR/lambda-package/lambda_delete_storage.py"
create_zip_from_dir "$BUILD_DIR/lambda-package" "$BUILD_DIR/lambda-package.zip"

cat > "$BUILD_DIR/lambda-env.json" <<EOF
{
  "Variables": {
    "FILES_TABLE": "$FILES_TABLE",
    "TAG_INDEX_TABLE": "$TAG_INDEX_TABLE",
    "GCP_COPY_ENDPOINT": "${GCP_COPY_ENDPOINT:-}",
    "GCP_COPY_SECRET": "${GCP_COPY_SECRET:-}"
  }
}
EOF

echo "Creating/updating delete Lambda..."

if aws lambda get-function --function-name "$DELETE_LAMBDA_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "Lambda exists. Updating code and configuration..."

  aws lambda update-function-code \
    --function-name "$DELETE_LAMBDA_NAME" \
    --zip-file "fileb://$BUILD_DIR/lambda-package.zip" \
    --region "$REGION" >/dev/null

  aws lambda wait function-updated \
    --function-name "$DELETE_LAMBDA_NAME" \
    --region "$REGION"

  aws lambda update-function-configuration \
    --function-name "$DELETE_LAMBDA_NAME" \
    --runtime "$RUNTIME" \
    --handler "lambda_delete_storage.lambda_handler" \
    --role "$ROLE_ARN" \
    --timeout "$TIMEOUT" \
    --memory-size "$MEMORY_SIZE" \
    --environment "file://$BUILD_DIR/lambda-env.json" \
    --region "$REGION" >/dev/null

  aws lambda wait function-updated \
    --function-name "$DELETE_LAMBDA_NAME" \
    --region "$REGION"
else
  echo "Lambda does not exist. Creating new function..."

  aws lambda create-function \
    --function-name "$DELETE_LAMBDA_NAME" \
    --runtime "$RUNTIME" \
    --handler "lambda_delete_storage.lambda_handler" \
    --role "$ROLE_ARN" \
    --zip-file "fileb://$BUILD_DIR/lambda-package.zip" \
    --timeout "$TIMEOUT" \
    --memory-size "$MEMORY_SIZE" \
    --environment "file://$BUILD_DIR/lambda-env.json" \
    --region "$REGION" >/dev/null
fi

aws lambda wait function-active \
  --function-name "$DELETE_LAMBDA_NAME" \
  --region "$REGION"

DELETE_LAMBDA_ARN="$(aws lambda get-function \
  --function-name "$DELETE_LAMBDA_NAME" \
  --region "$REGION" \
  --query 'Configuration.FunctionArn' \
  --output text)"

echo "=========================================="
echo "P2 delete deployment completed successfully"
echo "Lambda: $DELETE_LAMBDA_NAME"
echo "Lambda ARN: $DELETE_LAMBDA_ARN"
echo "=========================================="
