import base64
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import unquote, urlparse

import uuid
from email.parser import BytesParser
from email.policy import default

import boto3
from boto3.dynamodb.conditions import Attr, Key


dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")

lambda_client = boto3.client("lambda")

QUERY_FILE_BUCKET = os.environ.get("QUERY_FILE_BUCKET", "a2-group92-p2-media-909774767032")
TAGGING_LAMBDA_NAME = os.environ.get("TAGGING_LAMBDA_NAME", "a2-group92-tagging")

FILES_TABLE = os.environ.get("FILES_TABLE", "a2_group92_files")
TAG_INDEX_TABLE = os.environ.get("TAG_INDEX_TABLE", "a2_group92_tag_index")
ACTION = os.environ.get("ACTION", "")
PRESIGNED_URL_EXPIRY = int(os.environ.get("PRESIGNED_URL_EXPIRY", "900"))

files_table = dynamodb.Table(FILES_TABLE)
tag_index_table = dynamodb.Table(TAG_INDEX_TABLE)


def to_plain(value):
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {key: to_plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_plain(item) for item in value]
    return value


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
        },
        "body": json.dumps(to_plain(body)),
    }


def parse_body(event):
    if event.get("httpMethod") == "OPTIONS":
        return {}

    if is_multipart_event(event):
        return {}

    query_params = event.get("queryStringParameters")
    if isinstance(query_params, dict) and query_params:
        return query_params

    body = event.get("body")

    if body is None:
        return event if isinstance(event, dict) else {}

    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")

    if isinstance(body, str) and body.strip():
        return json.loads(body)

    if isinstance(body, dict):
        return body

    return {}

def get_header(event, header_name):
    headers = event.get("headers") or {}

    for key, value in headers.items():
        if key.lower() == header_name.lower():
            return value

    return ""


def is_multipart_event(event):
    content_type = get_header(event, "content-type")
    return "multipart/form-data" in content_type.lower()


def parse_multipart_file(event):
    content_type = get_header(event, "content-type")

    if not content_type:
        raise ValueError("Missing Content-Type header")

    body = event.get("body", "")

    if event.get("isBase64Encoded"):
        body_bytes = base64.b64decode(body)
    else:
        try:
            body_bytes = body.encode("latin1")
        except UnicodeEncodeError:
            body_bytes = body.encode("utf-8")

    message_bytes = (
        f"Content-Type: {content_type}\r\n"
        "MIME-Version: 1.0\r\n\r\n"
    ).encode("utf-8") + body_bytes

    message = BytesParser(policy=default).parsebytes(message_bytes)

    for part in message.iter_parts():
        content_disposition = part.get("Content-Disposition", "")

        if 'name="file"' in content_disposition:
            filename = part.get_filename() or "query_upload"
            mime_type = part.get_content_type()
            file_bytes = part.get_payload(decode=True)

            if not file_bytes:
                raise ValueError("Uploaded file is empty")

            return filename, mime_type, file_bytes

    raise ValueError("Missing multipart field: file")


def detect_tags_from_multipart_event(event):
    filename, mime_type, file_bytes = parse_multipart_file(event)

    if mime_type.startswith("image/"):
        file_type = "image"
    elif mime_type.startswith("video/"):
        file_type = "video"
    else:
        raise ValueError(f"Unsupported file MIME type: {mime_type}")

    safe_filename = filename.replace("/", "_").replace("\\", "_")
    temp_file_id = f"query_{uuid.uuid4().hex}"
    temp_key = f"query-files/{temp_file_id}_{safe_filename}"

    s3_client.put_object(
        Bucket=QUERY_FILE_BUCKET,
        Key=temp_key,
        Body=file_bytes,
        ContentType=mime_type,
    )

    try:
        tagging_payload = {
            "mode": "detect_only",
            "file_id": temp_file_id,
            "bucket": QUERY_FILE_BUCKET,
            "object_key": temp_key,
            "file_type": file_type,
            "mime_type": mime_type,
        }

        result = lambda_client.invoke(
            FunctionName=TAGGING_LAMBDA_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps(tagging_payload).encode("utf-8"),
        )

        raw_payload = result["Payload"].read().decode("utf-8")
        lambda_response = json.loads(raw_payload)
        response_body = json.loads(lambda_response.get("body", "{}"))

        if lambda_response.get("statusCode") != 200:
            raise ValueError(response_body.get("message", "Tag detection failed"))

        tags = response_body.get("tags", {})

        if not tags:
            raise ValueError("No tags detected from query file")

        return {str(tag): int(count) for tag, count in tags.items()}

    finally:
        s3_client.delete_object(
            Bucket=QUERY_FILE_BUCKET,
            Key=temp_key,
        )


def scan_all(table, filter_expression):
    items = []
    kwargs = {"FilterExpression": filter_expression}

    while True:
        result = table.scan(**kwargs)
        items.extend(result.get("Items", []))

        last_key = result.get("LastEvaluatedKey")
        if not last_key:
            break

        kwargs["ExclusiveStartKey"] = last_key

    return items


def query_tag_index(tag, min_count=1):
    items = []
    kwargs = {
        "KeyConditionExpression": Key("tag").eq(tag),
        "FilterExpression": Attr("count").gte(Decimal(str(min_count))),
    }

    while True:
        result = tag_index_table.query(**kwargs)
        items.extend(result.get("Items", []))

        last_key = result.get("LastEvaluatedKey")
        if not last_key:
            break

        kwargs["ExclusiveStartKey"] = last_key

    return items


def normalise_tag_counts(data):
    raw_tags = data.get("tags")

    if isinstance(raw_tags, dict):
        return {str(tag): int(count) for tag, count in raw_tags.items()}

    if isinstance(raw_tags, list):
        return {str(tag): 1 for tag in raw_tags}

    reserved_keys = {
        "urls",
        "url",
        "thumbnail_url",
        "full_url",
        "operation",
        "file_id",
        "file_type",
        "mime_type",
    }

    tag_counts = {}
    for key, value in data.items():
        if key not in reserved_keys and isinstance(value, (int, float, str)):
            try:
                tag_counts[str(key)] = int(value)
            except ValueError:
                pass

    return tag_counts


def get_file_item(file_id):
    result = files_table.get_item(Key={"file_id": file_id})
    return result.get("Item")


def parse_s3_reference(value):
    if not value:
        return None, None

    parsed = urlparse(value)
    path = unquote(parsed.path.lstrip("/"))

    if not parsed.scheme and path.startswith("thumbnails/"):
        return None, path

    if parsed.scheme == "s3":
        return parsed.netloc, path

    if parsed.scheme in ["http", "https"]:
        host = parsed.netloc

        if ".s3" in host:
            return host.split(".s3")[0], path

        if host.startswith("s3."):
            parts = path.split("/", 1)
            if len(parts) == 2:
                return parts[0], parts[1]

    return None, None


def presign_s3_url(bucket, object_key):
    if not bucket or not object_key:
        return ""

    try:
        return s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": object_key},
            ExpiresIn=PRESIGNED_URL_EXPIRY,
        )
    except Exception:
        return f"s3://{bucket}/{object_key}"


def resolve_bucket_key(item, key_fields, url_fields=()):
    bucket = item.get("bucket", "")

    for key_field in key_fields:
        object_key = item.get(key_field)
        if bucket and object_key:
            return bucket, object_key

    for url_field in url_fields:
        parsed_bucket, parsed_key = parse_s3_reference(item.get(url_field, ""))
        if parsed_bucket and parsed_key:
            return parsed_bucket, parsed_key

    return None, None


def build_result_from_file(item):
    full_bucket, full_key = resolve_bucket_key(
        item,
        ["object_key"],
        ["full_url", "s3_uri"],
    )
    thumbnail_bucket, thumbnail_key = resolve_bucket_key(
        item,
        ["thumbnail_key"],
        ["thumbnail_url"],
    )
    file_url = presign_s3_url(full_bucket, full_key)
    thumbnail_url = presign_s3_url(thumbnail_bucket, thumbnail_key)
    video_frame_keys = item.get("video_frame_keys", [])
    video_frame_urls = []

    if isinstance(video_frame_keys, list):
        for frame_key in video_frame_keys:
            frame_url = presign_s3_url(item.get("bucket", ""), frame_key)
            if frame_url:
                video_frame_urls.append(frame_url)

    if not video_frame_urls:
        raw_frame_urls = item.get("video_frame_urls", [])
        if isinstance(raw_frame_urls, list):
            for raw_url in raw_frame_urls:
                frame_bucket, frame_key = parse_s3_reference(raw_url)
                frame_url = presign_s3_url(frame_bucket, frame_key)
                video_frame_urls.append(frame_url or raw_url)

    return {
        "file_id": item.get("file_id"),
        "file_type": item.get("file_type"),
        "mime_type": item.get("mime_type"),
        "tags": item.get("tags", {}),
        "thumbnail_url": thumbnail_url or item.get("thumbnail_url", ""),
        "file_url": file_url or item.get("full_url", ""),
        "full_url": file_url or item.get("full_url", ""),
        "storage_url": item.get("full_url", item.get("s3_uri", "")),
        "video_frame_keys": video_frame_keys,
        "video_frame_urls": video_frame_urls,
        "frame_count": item.get("frame_count", len(video_frame_urls)),
        "bucket": item.get("bucket", ""),
        "object_key": item.get("object_key", ""),
        "secondary_provider": item.get("secondary_provider", ""),
        "secondary_bucket": item.get("secondary_bucket", ""),
        "secondary_full_url": item.get("secondary_full_url", ""),
        "secondary_thumbnail_url": item.get("secondary_thumbnail_url", ""),
        "secondary_frame_urls": item.get("secondary_frame_urls", []),
        "secondary_object_key": item.get("secondary_object_key", ""),
        "secondary_thumbnail_key": item.get("secondary_thumbnail_key", ""),
        "secondary_frame_keys": item.get("secondary_frame_keys", []),
        "secondary_copy_status": item.get("secondary_copy_status", ""),
    }


def query_files_by_tags(tag_counts):
    if not tag_counts:
        return []

    matched_sets = []
    index_items_by_file_id = {}

    for tag, min_count in tag_counts.items():
        index_items = query_tag_index(tag, min_count)
        file_ids = set()

        for item in index_items:
            file_id = item.get("file_id")
            if file_id:
                file_ids.add(file_id)
                index_items_by_file_id[file_id] = item

        matched_sets.append(file_ids)

    if not matched_sets:
        return []

    common_file_ids = set.intersection(*matched_sets)

    results = []
    for file_id in sorted(common_file_ids):
        file_item = get_file_item(file_id)

        if file_item:
            results.append(build_result_from_file(file_item))
        else:
            index_item = index_items_by_file_id.get(file_id, {})
            results.append(build_result_from_file({"file_id": file_id, **index_item}))

    return results


def handle_query_tags(data):
    tag_counts = normalise_tag_counts(data)
    results = query_files_by_tags(tag_counts)

    return response(200, {
        "status": "success",
        "query": tag_counts,
        "count": len(results),
        "results": results,
    })


def handle_query_species(data):
    species = data.get("species") or data.get("tag")

    if not species and len(data) == 1:
        species = next(iter(data.keys()))

    if not species:
        return response(400, {
            "status": "error",
            "message": "Missing species or tag",
        })

    results = query_files_by_tags({str(species): 1})

    return response(200, {
        "status": "success",
        "species": species,
        "count": len(results),
        "results": results,
    })


def handle_query_thumbnail(data):
    thumbnail_url = data.get("thumbnail_url") or data.get("url")

    if not thumbnail_url:
        return response(400, {
            "status": "error",
            "message": "Missing thumbnail_url",
        })

    thumbnail_bucket, thumbnail_key = parse_s3_reference(thumbnail_url)
    filter_expression = Attr("thumbnail_url").eq(thumbnail_url)

    if thumbnail_key:
        filter_expression = filter_expression | Attr("thumbnail_key").eq(thumbnail_key)

    items = scan_all(files_table, filter_expression)

    if not items:
        return response(404, {
            "status": "error",
            "message": "No file found for thumbnail_url",
        })

    item = items[0]

    result = build_result_from_file(item)

    return response(200, {
        "status": "success",
        "thumbnail_url": result.get("thumbnail_url", thumbnail_url),
        "file_url": result.get("file_url", ""),
        "full_url": result.get("full_url", ""),
        "file_id": result.get("file_id"),
        "file_type": result.get("file_type"),
        "mime_type": result.get("mime_type"),
    })


def handle_query_file(data, event=None):
    if event and is_multipart_event(event):
        tag_counts = detect_tags_from_multipart_event(event)
    else:
        tag_counts = normalise_tag_counts(data)

    if not tag_counts:
        return response(400, {
            "status": "error",
            "message": "query/file requires either multipart field 'file' or JSON tags. Example: {'tags': ['koala', 'wombat']}",
        })

    results = query_files_by_tags(tag_counts)

    return response(200, {
        "status": "success",
        "detected_tags": tag_counts,
        "count": len(results),
        "results": results,
        "note": "The query file is not stored permanently by this Lambda.",
    })


def find_file_by_url(url):
    items = scan_all(
        files_table,
        Attr("full_url").eq(url) | Attr("thumbnail_url").eq(url)
    )

    if items:
        return items[0]

    parsed_bucket, parsed_key = parse_s3_reference(url)

    if parsed_key:
        filter_expression = (
            Attr("object_key").eq(parsed_key)
            | Attr("thumbnail_key").eq(parsed_key)
            | Attr("s3_uri").eq(f"s3://{parsed_bucket}/{parsed_key}")
            | Attr("full_url").eq(f"s3://{parsed_bucket}/{parsed_key}")
        )

        if parsed_bucket:
            filter_expression = filter_expression | (
                Attr("bucket").eq(parsed_bucket) & Attr("object_key").eq(parsed_key)
            )

        items = scan_all(files_table, filter_expression)

        if items:
            return items[0]

    return None


def normalise_tag_list(data):
    raw_tags = data.get("tags", [])

    if isinstance(raw_tags, dict):
        return {str(tag): int(count) for tag, count in raw_tags.items()}

    if isinstance(raw_tags, list):
        return {str(tag): 1 for tag in raw_tags}

    if isinstance(raw_tags, str):
        return {raw_tags: 1}

    return {}


def handle_tags_edit(data):
    urls = data.get("urls") or data.get("url") or []
    operation = int(data.get("operation", -1))
    tag_counts = normalise_tag_list(data)

    if isinstance(urls, str):
        urls = [urls]

    if not urls:
        return response(400, {
            "status": "error",
            "message": "Missing urls",
        })

    if operation not in [0, 1]:
        return response(400, {
            "status": "error",
            "message": "operation must be 1 for add or 0 for remove",
        })

    if not tag_counts:
        return response(400, {
            "status": "error",
            "message": "Missing tags",
        })

    updated_files = []
    not_found = []

    for url in urls:
        item = find_file_by_url(url)

        if not item:
            not_found.append(url)
            continue

        file_id = item["file_id"]
        current_tags = dict(item.get("tags", {}))

        if operation == 1:
            for tag, count in tag_counts.items():
                current_tags[tag] = int(count)

                tag_index_table.put_item(Item={
                    "tag": tag,
                    "file_id": file_id,
                    "count": int(count),
                    "file_type": item.get("file_type", ""),
                    "mime_type": item.get("mime_type", ""),
                    "thumbnail_url": item.get("thumbnail_url", ""),
                    "full_url": item.get("full_url", ""),
                    "s3_uri": item.get("s3_uri", ""),
                    "uploaded_at": item.get("uploaded_at", ""),
                })
        else:
            for tag in tag_counts:
                if tag in current_tags:
                    del current_tags[tag]

                tag_index_table.delete_item(
                    Key={
                        "tag": tag,
                        "file_id": file_id,
                    }
                )

        item["tags"] = current_tags
        item["updated_at"] = datetime.now(timezone.utc).isoformat()
        files_table.put_item(Item=item)
        updated_files.append(file_id)

    return response(200, {
        "status": "success",
        "operation": operation,
        "updated_files": updated_files,
        "not_found": not_found,
    })


def parse_s3_url(url):
    if not url:
        return None, None

    parsed = urlparse(url)
    host = parsed.netloc
    path = unquote(parsed.path.lstrip("/"))

    if ".s3.amazonaws.com" in host:
        bucket = host.split(".s3.amazonaws.com")[0]
        return bucket, path

    if host.startswith("s3.amazonaws.com"):
        parts = path.split("/", 1)
        if len(parts) == 2:
            return parts[0], parts[1]

    return None, None


def safe_delete_s3_object(bucket, object_key):
    if not bucket or not object_key:
        return False

    try:
        s3_client.delete_object(Bucket=bucket, Key=object_key)
        return True
    except Exception:
        return False


def handle_delete_files(data):
    urls = data.get("urls") or data.get("url") or []

    if isinstance(urls, str):
        urls = [urls]

    if not urls:
        return response(400, {
            "status": "error",
            "message": "Missing urls",
        })

    deleted = []
    not_found = []

    for url in urls:
        item = find_file_by_url(url)

        if not item:
            not_found.append(url)
            continue

        file_id = item["file_id"]
        tags = item.get("tags", {})

        bucket = item.get("bucket", "")
        object_key = item.get("object_key", "")
        safe_delete_s3_object(bucket, object_key)

        thumbnail_url = item.get("thumbnail_url", "")
        thumbnail_bucket, thumbnail_key = parse_s3_url(thumbnail_url)
        safe_delete_s3_object(thumbnail_bucket, thumbnail_key)

        for tag in tags:
            tag_index_table.delete_item(
                Key={
                    "tag": tag,
                    "file_id": file_id,
                }
            )

        files_table.delete_item(Key={"file_id": file_id})
        deleted.append(file_id)

    return response(200, {
        "status": "success",
        "deleted_files": deleted,
        "not_found": not_found,
    })


def lambda_handler(event, context):
    try:
        if event.get("httpMethod") == "OPTIONS":
            return response(200, {"status": "ok"})

        action = ACTION

        if action == "query_file" and is_multipart_event(event):
            return handle_query_file({}, event)

        data = parse_body(event)

        if action == "query_tags":
            return handle_query_tags(data)
        if action == "query_species":
            return handle_query_species(data)
        if action == "query_thumbnail":
            return handle_query_thumbnail(data)
        if action == "query_file":
            return handle_query_file(data, event)
        if action == "tags_edit":
            return handle_tags_edit(data)
        if action == "delete_files":
            return handle_delete_files(data)

        return response(400, {
            "status": "error",
            "message": f"Unknown ACTION: {action}",
        })

    except Exception as error:
        return response(500, {
            "status": "error",
            "message": str(error),
        })
