import json
import os
import hashlib
import urllib.parse
import urllib.request
import mimetypes
import glob
import subprocess
import shutil
from datetime import datetime, timezone

import boto3
from PIL import Image, ImageOps
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")

FILES_TABLE = os.environ.get("FILES_TABLE", "a2_group92_files")
CHECKSUM_INDEX = os.environ.get("CHECKSUM_INDEX", "checksum_sha256-index")
P3_LAMBDA_NAME = os.environ.get("P3_LAMBDA_NAME", "")
ENABLE_SECONDARY_STORAGE = os.environ.get("ENABLE_SECONDARY_STORAGE", "false").lower() == "true"
SECONDARY_PROVIDER = os.environ.get("SECONDARY_PROVIDER", "gcp")
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")
GCP_COPY_ENDPOINT = os.environ.get("GCP_COPY_ENDPOINT", "")
GCP_COPY_SECRET = os.environ.get("GCP_COPY_SECRET", "")
PRESIGNED_URL_EXPIRES_SECONDS = int(os.environ.get("PRESIGNED_URL_EXPIRES_SECONDS", "900"))

files_table = dynamodb.Table(FILES_TABLE)


def calculate_sha256(bucket_name, object_key):
    response = s3.get_object(Bucket=bucket_name, Key=object_key)

    sha256 = hashlib.sha256()
    for chunk in response["Body"].iter_chunks(chunk_size=1024 * 1024):
        if chunk:
            sha256.update(chunk)

    return sha256.hexdigest()


def find_existing_file_by_checksum(checksum_sha256):
    direct_response = files_table.get_item(Key={"file_id": checksum_sha256})
    direct_item = direct_response.get("Item")

    if direct_item:
        return direct_item

    response = files_table.query(
        IndexName=CHECKSUM_INDEX,
        KeyConditionExpression=Key("checksum_sha256").eq(checksum_sha256),
        Limit=1
    )

    items = response.get("Items", [])
    if items:
        return items[0]

    return None


def reserve_new_file_record(
    file_id,
    bucket_name,
    object_key,
    file_type,
    mime_type,
    object_size,
    checksum_sha256,
    uploaded_at
):
    try:
        files_table.put_item(
            Item={
                "file_id": file_id,
                "bucket": bucket_name,
                "object_key": object_key,
                "s3_uri": f"s3://{bucket_name}/{object_key}",
                "file_type": file_type,
                "mime_type": mime_type,
                "file_size": object_size,
                "checksum": checksum_sha256,
                "checksum_sha256": checksum_sha256,
                "uploaded_at": uploaded_at,
                "tags": {},
                "thumbnail_key": "",
                "thumbnail_url": "",
                "video_frame_keys": [],
                "video_frame_urls": [],
                "frame_count": 0,
                "full_url": f"s3://{bucket_name}/{object_key}",
                "processing_status": "processing_started",
            },
            ConditionExpression="attribute_not_exists(file_id)",
        )
        return None
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return find_existing_file_by_checksum(checksum_sha256)
        raise


def detect_mime_type(object_key):
    content_type, _ = mimetypes.guess_type(object_key)

    if content_type:
        return content_type

    return "application/octet-stream"


def detect_file_type(object_key):
    content_type, _ = mimetypes.guess_type(object_key)

    if content_type and content_type.startswith("image/"):
        return "image"

    if content_type and content_type.startswith("video/"):
        return "video"

    lower_key = object_key.lower()

    if lower_key.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return "image"

    if lower_key.endswith((".mp4", ".mov", ".avi", ".mkv")):
        return "video"

    return "unknown"


def build_gcs_original_key(object_key, file_id):
    suffix = os.path.splitext(object_key)[1]
    if not suffix:
        suffix = ".bin"

    return f"uploads/{file_id}{suffix}"


def build_gcs_frame_key(frame_key, file_id):
    return f"frames/{file_id}/{os.path.basename(frame_key)}"


def copy_s3_object_to_secondary(bucket_name, object_key, gcs_object_key, content_type):
    if not ENABLE_SECONDARY_STORAGE:
        return {"status": "secondary_disabled"}

    if not GCP_COPY_ENDPOINT or not GCP_COPY_SECRET:
        return {
            "status": "secondary_not_configured",
            "message": "GCP_COPY_ENDPOINT or GCP_COPY_SECRET is missing"
        }

    source_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": object_key},
        ExpiresIn=PRESIGNED_URL_EXPIRES_SECONDS
    )

    request_body = json.dumps({
        "source_url": source_url,
        "gcs_object_key": gcs_object_key,
        "content_type": content_type or "application/octet-stream"
    }).encode("utf-8")

    request = urllib.request.Request(
        GCP_COPY_ENDPOINT,
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "X-Copy-Secret": GCP_COPY_SECRET
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            response_body = response.read().decode("utf-8")
            result = json.loads(response_body)
            result["status_code"] = response.status
            return result
    except Exception as error:
        print(f"Secondary storage copy failed for {object_key}: {error}")
        return {
            "status": "secondary_copy_failed",
            "object_key": object_key,
            "gcs_object_key": gcs_object_key,
            "error": str(error)
        }


def copy_processed_files_to_secondary(
    bucket_name,
    object_key,
    file_id,
    mime_type,
    thumbnail_result,
    video_frame_result
):
    if not ENABLE_SECONDARY_STORAGE:
        return {
            "metadata": {},
            "result": {"status": "secondary_disabled"}
        }

    print("Copying processed files to secondary GCP storage.")

    original_gcs_key = build_gcs_original_key(object_key, file_id)
    original_result = copy_s3_object_to_secondary(
        bucket_name,
        object_key,
        original_gcs_key,
        mime_type
    )

    thumbnail_key = thumbnail_result.get("thumbnail_key", "")
    thumbnail_copy = {}
    if thumbnail_key:
        thumbnail_copy = copy_s3_object_to_secondary(
            bucket_name,
            thumbnail_key,
            f"thumbnails/{file_id}.jpg",
            "image/jpeg"
        )

    secondary_frame_keys = []
    secondary_frame_urls = []
    frame_copy_results = []

    for frame_key in video_frame_result.get("frame_keys", []):
        frame_gcs_key = build_gcs_frame_key(frame_key, file_id)
        frame_result = copy_s3_object_to_secondary(
            bucket_name,
            frame_key,
            frame_gcs_key,
            "image/jpeg"
        )
        frame_copy_results.append(frame_result)

        if frame_result.get("status") == "success":
            secondary_frame_keys.append(frame_result.get("object_key", frame_gcs_key))
            secondary_frame_urls.append(frame_result.get("url", ""))

    metadata = {
        "secondary_provider": SECONDARY_PROVIDER,
        "secondary_bucket": original_result.get("bucket", GCS_BUCKET),
        "secondary_object_key": original_result.get("object_key", original_gcs_key),
        "secondary_full_url": original_result.get("url", ""),
        "secondary_thumbnail_key": thumbnail_copy.get("object_key", ""),
        "secondary_thumbnail_url": thumbnail_copy.get("url", ""),
        "secondary_frame_keys": secondary_frame_keys,
        "secondary_frame_urls": secondary_frame_urls,
        "secondary_frames_prefix": f"frames/{file_id}/" if secondary_frame_keys else "",
        "secondary_copy_status": "completed" if original_result.get("status") == "success" else original_result.get("status", "unknown")
    }

    return {
        "metadata": metadata,
        "result": {
            "original": original_result,
            "thumbnail": thumbnail_copy,
            "frames": frame_copy_results
        }
    }


def generate_thumbnail(bucket_name, object_key, file_id):
    input_ext = os.path.splitext(object_key)[1] or ".jpg"
    local_input = f"/tmp/{file_id}_input{input_ext}"
    local_output = f"/tmp/{file_id}_thumbnail.jpg"

    s3.download_file(bucket_name, object_key, local_input)

    with Image.open(local_input) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((300, 300))

        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA")
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        else:
            image = image.convert("RGB")

        image.save(local_output, "JPEG", quality=80, optimize=True)

    thumbnail_key = f"thumbnails/{file_id}.jpg"

    s3.upload_file(
        local_output,
        bucket_name,
        thumbnail_key,
        ExtraArgs={"ContentType": "image/jpeg"}
    )

    thumbnail_url = f"s3://{bucket_name}/{thumbnail_key}"

    print(f"Thumbnail created: {thumbnail_key}")

    return {
        "thumbnail_key": thumbnail_key,
        "thumbnail_url": thumbnail_url,
        "status": "created"
    }


def find_ffmpeg_path():
    print("Checking ffmpeg layer files.")

    if os.path.exists("/opt"):
        print("/opt contents:", os.listdir("/opt"))
    else:
        print("/opt does not exist.")

    if os.path.exists("/opt/bin"):
        print("/opt/bin contents:", os.listdir("/opt/bin"))
    else:
        print("/opt/bin does not exist.")

    possible_paths = [
        "/opt/bin/ffmpeg",
        "/opt/ffmpeg",
        shutil.which("ffmpeg")
    ]

    for path in possible_paths:
        if path and os.path.exists(path):
            print(f"ffmpeg found at: {path}")
            return path

    print("ffmpeg was not found in expected paths.")
    return None


def extract_video_frames(bucket_name, object_key, file_id):
    ffmpeg_path = find_ffmpeg_path()

    if not ffmpeg_path:
        print("ffmpeg is not available. Video frame extraction skipped.")
        return {
            "frame_keys": [],
            "frame_urls": [],
            "frame_count": 0,
            "status": "ffmpeg_missing"
        }

    input_ext = os.path.splitext(object_key)[1] or ".mp4"
    local_video = f"/tmp/{file_id}_video{input_ext}"
    frames_dir = f"/tmp/{file_id}_frames"

    os.makedirs(frames_dir, exist_ok=True)

    print("Downloading video from S3 to Lambda /tmp.")
    s3.download_file(bucket_name, object_key, local_video)

    output_pattern = f"{frames_dir}/frame_%04d.jpg"

    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel", "error",
        "-i", local_video,
        "-vf", "fps=1",
        "-q:v", "3",
        output_pattern
    ]

    print("Running ffmpeg command:")
    print(" ".join(command))

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True
    )

    if completed.returncode != 0:
        print("ffmpeg failed.")
        print(completed.stderr)

        return {
            "frame_keys": [],
            "frame_urls": [],
            "frame_count": 0,
            "status": "ffmpeg_failed",
            "error": completed.stderr
        }

    frame_keys = []
    frame_urls = []

    for frame_path in sorted(glob.glob(f"{frames_dir}/frame_*.jpg")):
        frame_name = os.path.basename(frame_path)
        frame_key = f"video-frames/{file_id}/{frame_name}"

        s3.upload_file(
            frame_path,
            bucket_name,
            frame_key,
            ExtraArgs={"ContentType": "image/jpeg"}
        )

        frame_keys.append(frame_key)
        frame_urls.append(f"s3://{bucket_name}/{frame_key}")

    print(f"Extracted {len(frame_keys)} video frames.")

    return {
        "frame_keys": frame_keys,
        "frame_urls": frame_urls,
        "frame_count": len(frame_keys),
        "status": "created"
    }


def build_metadata_payload(
    file_id,
    bucket_name,
    object_key,
    file_type,
    mime_type,
    object_size,
    checksum_sha256,
    uploaded_at,
    thumbnail_url,
    video_frame_keys,
    video_frame_urls,
    secondary_metadata=None
):
    payload = {
        "file_id": file_id,
        "bucket": bucket_name,
        "object_key": object_key,
        "s3_uri": f"s3://{bucket_name}/{object_key}",
        "file_type": file_type,
        "mime_type": mime_type,
        "file_size": object_size,
        "checksum": checksum_sha256,
        "checksum_sha256": checksum_sha256,
        "uploaded_at": uploaded_at,
        "thumbnail_url": thumbnail_url,
        "video_frame_keys": video_frame_keys,
        "video_frame_urls": video_frame_urls,
        "frame_count": len(video_frame_keys),
    }

    if secondary_metadata:
        payload.update(secondary_metadata)

    return payload


def build_p3_payload(file_id, bucket_name, object_key, file_type, metadata_payload):
    return {
        "file_id": file_id,
        "bucket": bucket_name,
        "object_key": object_key,
        "file_type": file_type,
        "checksum": metadata_payload.get("checksum", file_id),
        "checksum_sha256": metadata_payload.get("checksum_sha256", file_id),
        "mime_type": metadata_payload.get("mime_type", ""),
        "uploaded_at": metadata_payload.get("uploaded_at", ""),
        "thumbnail_url": metadata_payload.get("thumbnail_url", ""),
        "full_url": metadata_payload.get("full_url") or metadata_payload.get("s3_uri", ""),
        "s3_uri": metadata_payload.get("s3_uri", ""),
        "video_frame_keys": metadata_payload.get("video_frame_keys", []),
        "video_frame_urls": metadata_payload.get("video_frame_urls", []),
        "frame_count": metadata_payload.get(
            "frame_count",
            len(metadata_payload.get("video_frame_keys", []))
        ),
    }


def save_initial_metadata(payload, thumbnail_result, video_frame_result):
    if payload["file_type"] == "video" and video_frame_result.get("status") != "created":
        processing_status = "frame_extraction_failed"
    else:
        processing_status = "ready_for_tagging"

    item = {
        "file_id": payload["file_id"],
        "bucket": payload["bucket"],
        "object_key": payload["object_key"],
        "s3_uri": payload["s3_uri"],
        "file_type": payload["file_type"],
        "mime_type": payload.get("mime_type", ""),
        "file_size": payload["file_size"],
        "checksum": payload["checksum"],
        "checksum_sha256": payload["checksum_sha256"],
        "uploaded_at": payload["uploaded_at"],
        "tags": {},
        "thumbnail_key": thumbnail_result.get("thumbnail_key", ""),
        "thumbnail_url": thumbnail_result.get("thumbnail_url", ""),
        "video_frame_keys": video_frame_result.get("frame_keys", []),
        "video_frame_urls": video_frame_result.get("frame_urls", []),
        "frame_count": video_frame_result.get("frame_count", 0),
        "full_url": payload["s3_uri"],
        "processing_status": processing_status
    }

    for key in [
        "secondary_provider",
        "secondary_bucket",
        "secondary_object_key",
        "secondary_full_url",
        "secondary_thumbnail_key",
        "secondary_thumbnail_url",
        "secondary_frame_keys",
        "secondary_frame_urls",
        "secondary_frames_prefix",
        "secondary_copy_status"
    ]:
        if key in payload:
            item[key] = payload[key]

    files_table.put_item(Item=item)


def invoke_p3_lambda(payload):
    print("P3 handoff payload:")
    print(json.dumps(payload))

    if not P3_LAMBDA_NAME:
        print("P3_LAMBDA_NAME is not configured yet. Payload is logged only.")
        return {
            "status": "p3_not_configured",
            "payload_logged": True
        }

    try:
        response = lambda_client.invoke(
            FunctionName=P3_LAMBDA_NAME,
            InvocationType="Event",
            Payload=json.dumps(payload).encode("utf-8")
        )

        return {
            "status": "p3_invoked",
            "lambda_status_code": response.get("StatusCode")
        }

    except Exception as error:
        print("Failed to invoke P3 Lambda.")
        print(str(error))

        return {
            "status": "p3_invoke_failed",
            "error": str(error)
        }


def lambda_handler(event, context):
    print("P2 S3 upload, SHA256 file_id, thumbnail, video frame extraction, metadata, and P3 handoff Lambda triggered")
    print("Full S3 event:")
    print(json.dumps(event))

    results = []

    for record in event.get("Records", []):
        bucket_name = record["s3"]["bucket"]["name"]
        object_key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        object_size = record["s3"]["object"].get("size", 0)

        print("Uploaded file information:")
        print(f"Bucket: {bucket_name}")
        print(f"Key: {object_key}")
        print(f"Size: {object_size} bytes")

        if object_key.endswith("/"):
            print("Folder object ignored.")
            continue

        if not object_key.startswith("uploads/"):
            print("Object is not in uploads/, ignored.")
            continue

        checksum_sha256 = calculate_sha256(bucket_name, object_key)
        print(f"SHA256 checksum: {checksum_sha256}")

        file_id = checksum_sha256
        file_type = detect_file_type(object_key)
        mime_type = detect_mime_type(object_key)

        print(f"Detected file_type: {file_type}")
        print(f"Detected mime_type: {mime_type}")

        if file_type not in ("image", "video"):
            print("Unsupported file type. Deleting uploaded object.")

            s3.delete_object(
                Bucket=bucket_name,
                Key=object_key
            )

            result = {
                "file_id": file_id,
                "key": object_key,
                "file_type": file_type,
                "mime_type": mime_type,
                "status": "unsupported_file_type_deleted"
            }

            print("Processing result:")
            print(json.dumps(result))

            results.append(result)
            continue

        uploaded_at = datetime.now(timezone.utc).isoformat()
        existing_file = find_existing_file_by_checksum(checksum_sha256)

        if not existing_file:
            existing_file = reserve_new_file_record(
                file_id=file_id,
                bucket_name=bucket_name,
                object_key=object_key,
                file_type=file_type,
                mime_type=mime_type,
                object_size=object_size,
                checksum_sha256=checksum_sha256,
                uploaded_at=uploaded_at
            )

        if existing_file:
            print("Duplicate file detected from a2_group92_files.")
            print(f"Existing file_id: {existing_file.get('file_id')}")
            print("Deleting the newly uploaded duplicate file.")

            s3.delete_object(
                Bucket=bucket_name,
                Key=object_key
            )

            result = {
                "file_id": file_id,
                "key": object_key,
                "checksum": checksum_sha256,
                "status": "duplicate_deleted",
                "existing_file_id": existing_file.get("file_id")
            }

        else:
            print("New file accepted. No existing checksum found in a2_group92_files.")

            thumbnail_result = {
                "thumbnail_key": "",
                "thumbnail_url": "",
                "status": "not_applicable"
            }

            video_frame_result = {
                "frame_keys": [],
                "frame_urls": [],
                "frame_count": 0,
                "status": "not_applicable"
            }

            if file_type == "image":
                print("Image file detected. Generating thumbnail.")
                thumbnail_result = generate_thumbnail(bucket_name, object_key, file_id)

            elif file_type == "video":
                print("Video file detected. Extracting frames at 1 frame per second.")
                video_frame_result = extract_video_frames(bucket_name, object_key, file_id)

            secondary_copy = copy_processed_files_to_secondary(
                bucket_name=bucket_name,
                object_key=object_key,
                file_id=file_id,
                mime_type=mime_type,
                thumbnail_result=thumbnail_result,
                video_frame_result=video_frame_result
            )

            metadata_payload = build_metadata_payload(
                file_id=file_id,
                bucket_name=bucket_name,
                object_key=object_key,
                file_type=file_type,
                mime_type=mime_type,
                object_size=object_size,
                checksum_sha256=checksum_sha256,
                uploaded_at=uploaded_at,
                thumbnail_url=thumbnail_result.get("thumbnail_url", ""),
                video_frame_keys=video_frame_result.get("frame_keys", []),
                video_frame_urls=video_frame_result.get("frame_urls", []),
                secondary_metadata=secondary_copy.get("metadata", {})
            )

            print("Saving initial file metadata to a2_group92_files.")
            save_initial_metadata(metadata_payload, thumbnail_result, video_frame_result)

            p3_payload = build_p3_payload(
                file_id=file_id,
                bucket_name=bucket_name,
                object_key=object_key,
                file_type=file_type,
                metadata_payload=metadata_payload
            )

            print("Preparing P3 handoff.")
            p3_result = invoke_p3_lambda(p3_payload)

            result = {
                "file_id": file_id,
                "key": object_key,
                "checksum": checksum_sha256,
                "checksum_sha256": checksum_sha256,
                "file_type": file_type,
                "mime_type": mime_type,
                "thumbnail_key": thumbnail_result.get("thumbnail_key", ""),
                "thumbnail_url": thumbnail_result.get("thumbnail_url", ""),
                "video_frame_keys": video_frame_result.get("frame_keys", []),
                "video_frame_urls": video_frame_result.get("frame_urls", []),
                "frame_count": video_frame_result.get("frame_count", 0),
                "status": "accepted_ready_for_tagging",
                "secondary_storage": secondary_copy.get("result", {}),
                "p3_payload": p3_payload,
                "p3_handoff": p3_result
            }

        print("Processing result:")
        print(json.dumps(result))

        results.append(result)

    return {
        "statusCode": 200,
        "body": json.dumps(results)
    }
