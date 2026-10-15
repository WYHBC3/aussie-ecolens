import json
import os
import urllib.request
from datetime import timedelta

import functions_framework
import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.cloud import storage


GCS_BUCKET = os.environ.get("GCS_BUCKET")
COPY_SECRET = os.environ.get("COPY_SECRET")
SIGNED_URL_EXPIRES_SECONDS = int(os.environ.get("SIGNED_URL_EXPIRES_SECONDS", "900"))
GCP_SIGNING_SERVICE_ACCOUNT = os.environ.get("GCP_SIGNING_SERVICE_ACCOUNT", "")


def json_response(payload, status_code):
    return (
        json.dumps(payload),
        status_code,
        {"Content-Type": "application/json"},
    )


def signed_gcs_url(blob):
    expiration = timedelta(seconds=SIGNED_URL_EXPIRES_SECONDS)

    try:
        return blob.generate_signed_url(
            version="v4",
            expiration=expiration,
            method="GET",
        )
    except Exception as first_error:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(GoogleAuthRequest())
        service_account_email = (
            GCP_SIGNING_SERVICE_ACCOUNT
            or getattr(credentials, "service_account_email", None)
        )

        if not service_account_email:
            raise first_error

        return blob.generate_signed_url(
            version="v4",
            expiration=expiration,
            method="GET",
            service_account_email=service_account_email,
            access_token=credentials.token,
        )


@functions_framework.http
def copy_s3_to_gcs(request):
    if not COPY_SECRET or request.headers.get("X-Copy-Secret") != COPY_SECRET:
        return json_response(
            {"status": "error", "message": "Unauthorized"},
            401,
        )

    data = request.get_json(silent=True) or {}
    operation = data.get("operation", "copy")

    if operation == "delete":
        return delete_gcs_objects(data)

    source_url = data.get("source_url")
    gcs_object_key = data.get("gcs_object_key")
    content_type = data.get("content_type", "application/octet-stream")

    if not source_url or not gcs_object_key:
        return json_response(
            {"status": "error", "message": "Missing source_url or gcs_object_key"},
            400,
        )

    if not GCS_BUCKET:
        return json_response(
            {"status": "error", "message": "Missing GCS_BUCKET environment variable"},
            500,
        )

    storage_client = storage.Client()
    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(gcs_object_key)

    with urllib.request.urlopen(source_url, timeout=120) as response:
        file_bytes = response.read()

    blob.upload_from_string(file_bytes, content_type=content_type)

    public_gcs_url = f"https://storage.googleapis.com/{GCS_BUCKET}/{gcs_object_key}"
    signed_url = signed_gcs_url(blob)

    return json_response(
        {
            "status": "success",
            "provider": "gcp",
            "bucket": GCS_BUCKET,
            "object_key": gcs_object_key,
            "url": signed_url,
            "signed_url": signed_url,
            "public_url": public_gcs_url,
            "signed_url_expires_seconds": SIGNED_URL_EXPIRES_SECONDS,
        },
        200,
    )


def delete_gcs_objects(data):
    if not GCS_BUCKET:
        return json_response(
            {"status": "error", "message": "Missing GCS_BUCKET environment variable"},
            500,
        )

    object_keys = data.get("gcs_object_keys") or []
    prefixes = data.get("gcs_prefixes") or []

    if isinstance(object_keys, str):
        object_keys = [object_keys]

    if isinstance(prefixes, str):
        prefixes = [prefixes]

    if not object_keys and not prefixes:
        return json_response(
            {"status": "error", "message": "Missing gcs_object_keys or gcs_prefixes"},
            400,
        )

    storage_client = storage.Client()
    bucket = storage_client.bucket(GCS_BUCKET)

    deleted = []
    missing = []

    for object_key in sorted(set(filter(None, object_keys))):
        blob = bucket.blob(object_key)
        if blob.exists():
            blob.delete()
            deleted.append(object_key)
        else:
            missing.append(object_key)

    for prefix in sorted(set(filter(None, prefixes))):
        for blob in bucket.list_blobs(prefix=prefix):
            blob.delete()
            deleted.append(blob.name)

    return json_response(
        {
            "status": "success",
            "provider": "gcp",
            "bucket": GCS_BUCKET,
            "deleted": deleted,
            "missing": missing,
        },
        200,
    )
