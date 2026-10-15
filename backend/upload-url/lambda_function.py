"""
upload-url Lambda
=================

Issues short-lived S3 presigned PUT URLs so the browser can upload media
directly to the P2 media bucket, triggering the existing S3 ObjectCreated
pipeline (P2 ingest -> P3 tagging -> DynamoDB).

Route:  POST /upload  (behind API Gateway + cognito-authorizer)
Body:   {"filename": "koala.jpg", "content_type": "image/jpeg"}
Reply:  {"upload_url": "...", "object_key": "uploads/<uuid>.<ext>", ...}

The UUID in object_key is only a temporary upload key. The final file_id is
computed by the P2 S3 trigger from the uploaded bytes' SHA-256 checksum.

Environment variables
---------------------
S3_BUCKET   (required) - the P2 media bucket name.
URL_EXPIRY  (optional) - presigned URL TTL in seconds. Default 300.
"""

import json
import os
import re
import uuid

import boto3
from boto3.dynamodb.conditions import Key
from botocore.client import Config
from botocore.exceptions import ClientError


S3_BUCKET = os.environ["S3_BUCKET"]
URL_EXPIRY = int(os.environ.get("URL_EXPIRY", "300"))
FILES_TABLE = os.environ.get("FILES_TABLE", "a2_group92_files")
CHECKSUM_INDEX = os.environ.get("CHECKSUM_INDEX", "checksum_sha256-index")

# Region-specific signing keeps Signature V4 happy for cross-region clients.
s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
dynamodb = boto3.resource("dynamodb")
files_table = dynamodb.Table(FILES_TABLE)

# Conservative content-type allowlist. P2's pipeline handles images + videos.
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/webm",
}

# Used to derive a safe extension when the filename is missing one.
EXT_FALLBACK_BY_CT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/x-msvideo": "avi",
    "video/webm": "webm",
}

SAFE_EXT_RE = re.compile(r"^[a-zA-Z0-9]{1,8}$")


def _cors_headers():
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Authorization,Content-Type",
        "Access-Control-Allow-Methods": "POST,OPTIONS",
    }


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": _cors_headers(),
        "body": json.dumps(body),
    }


def _pick_extension(filename: str, content_type: str) -> str:
    """Return a safe lowercase extension (no dot)."""
    if filename and "." in filename:
        candidate = filename.rsplit(".", 1)[-1].lower()
        if SAFE_EXT_RE.match(candidate):
            return candidate
    return EXT_FALLBACK_BY_CT.get(content_type, "bin")


def _find_existing_file(checksum_sha256: str):
    if not checksum_sha256:
        return None

    direct_result = files_table.get_item(Key={"file_id": checksum_sha256})
    direct_item = direct_result.get("Item")

    if direct_item:
        return direct_item

    query_result = files_table.query(
        IndexName=CHECKSUM_INDEX,
        KeyConditionExpression=Key("checksum_sha256").eq(checksum_sha256),
        Limit=1,
    )
    items = query_result.get("Items", [])
    return items[0] if items else None


def lambda_handler(event, context):
    # API Gateway sends OPTIONS preflight to the Lambda when CORS is enabled
    # via the "Lambda proxy" integration. Reply 200 with the headers.
    if event.get("httpMethod") == "OPTIONS":
        return _response(200, {})

    # Parse and validate body
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"success": False, "error": "Invalid JSON body"})

    filename = (body.get("filename") or "").strip()
    content_type = (body.get("content_type") or "application/octet-stream").strip()
    checksum_sha256 = (body.get("checksum_sha256") or body.get("checksum") or "").strip().lower()

    if not filename:
        return _response(400, {"success": False, "error": "filename is required"})

    if content_type not in ALLOWED_CONTENT_TYPES:
        return _response(
            400,
            {
                "success": False,
                "error": f"Unsupported content_type '{content_type}'.",
                "allowed": sorted(ALLOWED_CONTENT_TYPES),
            },
        )

    if checksum_sha256 and not re.fullmatch(r"[0-9a-f]{64}", checksum_sha256):
        return _response(400, {"success": False, "error": "checksum_sha256 must be a 64-character hex SHA-256 value"})

    # Pull Cognito claims for owner tracking.
    # Note: object_key does NOT embed owner_id, because P2's pipeline only
    # processes prefix "uploads/" and we don't want to risk altering its
    # prefix expectations. owner_id is logged + returned so the API trail
    # is auditable.
    try:
        claims = event["requestContext"]["authorizer"]["claims"]
        owner_id = claims["sub"]
        owner_email = claims.get("email", "")
    except KeyError:
        return _response(401, {"success": False, "error": "Missing Cognito claims"})

    existing_file = _find_existing_file(checksum_sha256)
    if existing_file:
        return _response(
            200,
            {
                "success": True,
                "duplicate": True,
                "message": "This file has already been uploaded.",
                "data": {
                    "file_id": existing_file.get("file_id"),
                    "bucket": existing_file.get("bucket", S3_BUCKET),
                    "object_key": existing_file.get("object_key", ""),
                    "file_url": existing_file.get("full_url") or existing_file.get("s3_uri", ""),
                    "file_type": existing_file.get("file_type", ""),
                    "mime_type": existing_file.get("mime_type", ""),
                    "processing_status": existing_file.get("processing_status", ""),
                    "checksum_sha256": existing_file.get("checksum_sha256", checksum_sha256),
                },
            },
        )

    # Generate unique S3 key. Bucket-side P2 trigger listens on "uploads/".
    ext = _pick_extension(filename, content_type)
    file_uuid = str(uuid.uuid4())
    object_key = f"uploads/{file_uuid}.{ext}"

    # Generate presigned PUT URL. The browser must send the same
    # Content-Type header, otherwise S3 rejects the signature.
    try:
        upload_url = s3.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": S3_BUCKET,
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=URL_EXPIRY,
            HttpMethod="PUT",
        )
    except ClientError as exc:
        return _response(
            500,
            {
                "success": False,
                "error": f"Failed to generate presigned URL: {exc}",
            },
        )

    print(
        json.dumps(
            {
                "event": "upload_url_issued",
                "owner_id": owner_id,
                "owner_email": owner_email,
                "object_key": object_key,
                "content_type": content_type,
                "checksum_sha256": checksum_sha256,
                "expires_in": URL_EXPIRY,
            }
        )
    )

    return _response(
        200,
        {
            "success": True,
            "data": {
                "upload_url": upload_url,
                "bucket": S3_BUCKET,
                "object_key": object_key,
                "expires_in": URL_EXPIRY,
                "content_type": content_type,
                "uploaded_by": owner_id,
            },
            "instructions": (
                "PUT the raw file body to upload_url with the SAME "
                "Content-Type header you specified above. Do NOT include "
                "Authorization. Do NOT wrap the body in FormData."
            ),
        },
    )
