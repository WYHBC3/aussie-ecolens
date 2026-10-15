import json
import os
import urllib.request
from decimal import Decimal
from urllib.parse import unquote, urlparse

import boto3


REGION = os.environ.get("AWS_REGION", "us-east-1")
FILES_TABLE = os.environ.get("FILES_TABLE", "a2_group92_files")
TAG_INDEX_TABLE = os.environ.get("TAG_INDEX_TABLE", "a2_group92_tag_index")
GCP_COPY_ENDPOINT = os.environ.get("GCP_COPY_ENDPOINT", "")
GCP_COPY_SECRET = os.environ.get("GCP_COPY_SECRET", "")

s3 = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
files_table = dynamodb.Table(FILES_TABLE)
tag_index_table = dynamodb.Table(TAG_INDEX_TABLE)


def normalise_event(event):
    if isinstance(event, dict) and "body" in event:
        body = event["body"]
        if isinstance(body, str):
            return json.loads(body or "{}")
        return body or {}

    return event or {}


def response(status_code, payload):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(payload, default=json_default),
    }


def json_default(value):
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def parse_s3_uri(value):
    if not value or not isinstance(value, str) or not value.startswith("s3://"):
        return None, None

    parsed = urlparse(value)
    return parsed.netloc, parsed.path.lstrip("/")


def parse_s3_https_url(value):
    if not value or not isinstance(value, str):
        return None, None

    parsed = urlparse(value)
    host = parsed.netloc
    path = parsed.path.lstrip("/")

    if host.endswith(".s3.amazonaws.com"):
        return host.split(".s3.amazonaws.com")[0], path

    if host == "s3.amazonaws.com":
        parts = path.split("/", 1)
        if len(parts) == 2:
            return parts[0], parts[1]

    return None, None


def get_string_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    if isinstance(value, str):
        return [value]
    return []


def unique(values):
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def find_item_by_file_id(file_id):
    item = files_table.get_item(Key={"file_id": file_id}).get("Item")
    if item:
        return item
    return None


def find_item_by_url(url):
    parsed_bucket, parsed_key = parse_s3_uri(url)
    if not parsed_bucket:
        parsed_bucket, parsed_key = parse_s3_https_url(url)

    response_data = files_table.scan()

    while True:
        for item in response_data.get("Items", []):
            if item_matches_url(item, url, parsed_bucket, parsed_key):
                return item

        last_key = response_data.get("LastEvaluatedKey")
        if not last_key:
            break

        response_data = files_table.scan(ExclusiveStartKey=last_key)

    return None


def item_matches_url(item, url, parsed_bucket, parsed_key):
    candidate_values = [
        item.get("s3_uri"),
        item.get("full_url"),
        item.get("file_url"),
        item.get("secondary_full_url"),
        item.get("thumbnail_url"),
        item.get("secondary_thumbnail_url"),
    ]

    if url in candidate_values:
        return True

    if parsed_key and item.get("object_key") == parsed_key:
        if not parsed_bucket or item.get("bucket") == parsed_bucket:
            return True

    if parsed_key and item.get("thumbnail_key") == parsed_key:
        if not parsed_bucket or item.get("bucket") == parsed_bucket:
            return True

    if not parsed_key:
        return False

    secondary_keys = [
        item.get("secondary_object_key"),
        item.get("secondary_thumbnail_key"),
        *get_string_list(item.get("secondary_frame_keys")),
    ]

    return parsed_key in unique(secondary_keys)


def collect_s3_objects(item):
    bucket = item.get("bucket")
    object_keys = [
        item.get("object_key"),
        item.get("thumbnail_key"),
        *get_string_list(item.get("video_frame_keys")),
    ]

    for uri_field in ["s3_uri", "full_url", "thumbnail_url"]:
        uri_bucket, uri_key = parse_s3_uri(item.get(uri_field))
        if uri_key:
            object_keys.append(uri_key)
        if uri_bucket and not bucket:
            bucket = uri_bucket

    for frame_uri in get_string_list(item.get("video_frame_urls")):
        _, frame_key = parse_s3_uri(frame_uri)
        if frame_key:
            object_keys.append(frame_key)

    return bucket, unique(object_keys)


def collect_gcs_objects(item):
    object_keys = [
        item.get("secondary_object_key"),
        item.get("secondary_thumbnail_key"),
        *get_string_list(item.get("secondary_frame_keys")),
    ]

    prefixes = []
    if item.get("secondary_frames_prefix"):
        prefixes.append(item["secondary_frames_prefix"])

    return unique(object_keys), unique(prefixes)


def delete_s3_objects(bucket, object_keys):
    if not bucket or not object_keys:
        return {"deleted": [], "skipped": object_keys}

    deleted = []
    for object_key in object_keys:
        s3.delete_object(Bucket=bucket, Key=object_key)
        deleted.append(f"s3://{bucket}/{object_key}")

    return {"deleted": deleted, "skipped": []}


def delete_gcs_objects(object_keys, prefixes):
    if not object_keys and not prefixes:
        return {"status": "not_applicable", "deleted": []}

    if not GCP_COPY_ENDPOINT or not GCP_COPY_SECRET:
        return {
            "status": "not_configured",
            "message": "GCP_COPY_ENDPOINT or GCP_COPY_SECRET is missing",
            "object_keys": object_keys,
            "prefixes": prefixes,
        }

    request_body = json.dumps({
        "operation": "delete",
        "gcs_object_keys": object_keys,
        "gcs_prefixes": prefixes,
    }).encode("utf-8")

    request = urllib.request.Request(
        GCP_COPY_ENDPOINT,
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "X-Copy-Secret": GCP_COPY_SECRET,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=180) as result:
            response_body = result.read().decode("utf-8")
            payload = json.loads(response_body)
            payload["status_code"] = result.status
            return payload
    except Exception as error:
        return {
            "status": "delete_failed",
            "error": str(error),
            "object_keys": object_keys,
            "prefixes": prefixes,
        }


def delete_tag_index_entries(item):
    file_id = item["file_id"]
    tags = item.get("tags") or {}
    deleted = []

    for tag in tags:
        tag_index_table.delete_item(Key={"tag": tag, "file_id": file_id})
        deleted.append(tag)

    return deleted


def delete_file_record(file_id):
    files_table.delete_item(Key={"file_id": file_id})


def resolve_items(payload):
    items = []

    for file_id in payload.get("file_ids", []):
        item = find_item_by_file_id(file_id)
        items.append({"input": file_id, "item": item})

    for url in payload.get("urls", []):
        item = find_item_by_url(url)
        items.append({"input": url, "item": item})

    if payload.get("file_id"):
        item = find_item_by_file_id(payload["file_id"])
        items.append({"input": payload["file_id"], "item": item})

    if payload.get("url"):
        item = find_item_by_url(payload["url"])
        items.append({"input": payload["url"], "item": item})

    return items


def lambda_handler(event, context):
    payload = normalise_event(event)
    resolved_items = resolve_items(payload)

    if not resolved_items:
        return response(
            400,
            {
                "message": "Provide file_ids, urls, file_id, or url.",
                "example": {"file_ids": ["<sha256-file-id>"]},
            },
        )

    results = []
    deleted_count = 0

    for resolved in resolved_items:
        item = resolved["item"]
        if not item:
            results.append({
                "input": resolved["input"],
                "status": "not_found",
            })
            continue

        file_id = item["file_id"]
        bucket, s3_keys = collect_s3_objects(item)
        gcs_keys, gcs_prefixes = collect_gcs_objects(item)

        s3_result = delete_s3_objects(bucket, s3_keys)
        gcs_result = delete_gcs_objects(gcs_keys, gcs_prefixes)
        tag_index_deleted = delete_tag_index_entries(item)
        delete_file_record(file_id)

        deleted_count += 1
        results.append({
            "input": resolved["input"],
            "status": "deleted",
            "file_id": file_id,
            "s3": s3_result,
            "gcs": gcs_result,
            "tag_index_deleted": tag_index_deleted,
            "database_record_deleted": True,
        })

    return response(
        200,
        {
            "message": "Delete operation completed.",
            "deleted_count": deleted_count,
            "results": results,
        },
    )
