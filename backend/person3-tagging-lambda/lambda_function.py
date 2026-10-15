import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import boto3
import numpy as np
import torch
import torchvision.transforms as transforms
from PIL import Image


REGION = os.environ.get("AWS_REGION", "us-east-1")
FILES_TABLE = os.environ.get("FILES_TABLE", "a2_group92_files")
TAG_INDEX_TABLE = os.environ.get("TAG_INDEX_TABLE", "a2_group92_tag_index")
MODEL_PATH = Path(os.environ.get("MODEL_PATH", "/var/task/model.pt"))

s3_client = boto3.client("s3", region_name=REGION)
sns_client = boto3.client("sns")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
dynamodb = boto3.resource("dynamodb", region_name=REGION)

files_table = dynamodb.Table(FILES_TABLE)
tag_index_table = dynamodb.Table(TAG_INDEX_TABLE)

CLASSES = [
    "Alectura_lathami",
    "Antechinus_agilis",
    "Bos_taurus",
    "Burhinus_grallarius",
    "Canis_familiaris",
    "Chalcophaps_longirostris",
    "Colluricincla_harmonica",
    "Corcorax_melanorhamphos",
    "Dacelo_novaeguineae",
    "Dama_dama",
    "Eopsaltria_australis",
    "Felis_catus",
    "Geopelia_humeralis",
    "Gymnorhina_tibicen",
    "Homo_sapiens",
    "Isoodon_macrourus",
    "Lepus_europaeus",
    "Macropus_giganteus",
    "Menura_novaehollandiae",
    "Mus_musculus",
    "Oryctolagus_cuniculus",
    "Perameles_nasuta",
    "Pitta_versicolor",
    "Rattus",
    "Rattus_fuscipes",
    "Rattus_rattus",
    "Strepera_graculina",
    "Sus_scrofa",
    "Tachyglossus_aculeatus",
    "Thylogale_stigmatica",
    "Trichosurus_caninus",
    "Trichosurus_cunninghami",
    "Trichosurus_vulpecula",
    "Varanus_varius",
    "Vombatus_ursinus",
    "Vulpes_vulpes",
    "Wallabia_bicolor",
    "Canis_dingo",
    "Capra_hircus",
    "Casuarius_casuarius",
    "Heteromyias_cinereifrons",
    "Hypsiprymnodon_moschatus",
    "Megapodius_reinwardt",
    "Notamacropus_rufogriseus",
    "Orthonyx_spaldingii",
    "Uromys_caudimaculatus",
]

model = None

transform = transforms.Compose([
    transforms.Resize((480, 480)),
    transforms.ToTensor(),
])


def normalise_event(event):
    if isinstance(event, dict) and "body" in event:
        body = event["body"]
        if isinstance(body, str):
            return json.loads(body)
        return body

    return event


def load_model():
    global model

    if model is not None:
        return model

    loaded_model = torch.load(MODEL_PATH, map_location="cpu", weights_only=False)
    loaded_model.eval()

    model = loaded_model
    return model


def download_file(bucket, object_key, file_id):
    suffix = Path(object_key).suffix or ".jpg"
    local_path = Path("/tmp") / f"{file_id}{suffix}"

    s3_client.download_file(bucket, object_key, str(local_path))

    return local_path


def parse_s3_uri(value):
    if not isinstance(value, str) or not value.startswith("s3://"):
        return None, None

    without_scheme = value[5:]
    bucket, _, object_key = without_scheme.partition("/")

    if not bucket or not object_key:
        return None, None

    return bucket, object_key


@torch.no_grad()
def classify_image(image_path):
    loaded_model = load_model()

    image = Image.open(image_path).convert("RGB")
    image_tensor = transform(image)
    image_tensor = image_tensor.unsqueeze(0)
    image_tensor = image_tensor.permute(0, 2, 3, 1)

    logits = loaded_model(image_tensor)
    probs = torch.softmax(logits, dim=1)[0].cpu().numpy()

    best_idx = int(np.argmax(probs))
    species = CLASSES[best_idx].lower()
    confidence = Decimal(str(round(float(probs[best_idx]), 4)))

    return species, confidence


def collect_video_frame_references(payload):
    frame_references = []
    default_bucket = payload.get("bucket", "")
    file_id = payload.get("file_id", "")

    for frame_key in payload.get("video_frame_keys") or []:
        if isinstance(frame_key, str) and frame_key:
            frame_references.append((default_bucket, frame_key))

    for frame_url in payload.get("video_frame_urls") or []:
        frame_bucket, frame_key = parse_s3_uri(frame_url)
        if frame_bucket and frame_key:
            frame_references.append((frame_bucket, frame_key))

    if not frame_references and file_id:
        try:
            existing_result = files_table.get_item(Key={"file_id": file_id})
            existing_item = existing_result.get("Item", {})

            for frame_key in existing_item.get("video_frame_keys") or []:
                if isinstance(frame_key, str) and frame_key:
                    frame_references.append((default_bucket, frame_key))

            for frame_url in existing_item.get("video_frame_urls") or []:
                frame_bucket, frame_key = parse_s3_uri(frame_url)
                if frame_bucket and frame_key:
                    frame_references.append((frame_bucket, frame_key))
        except Exception as error:
            print(f"Could not load existing video frame references: {error}")

    if not frame_references and default_bucket and file_id:
        prefix = f"video-frames/{file_id}/"
        try:
            paginator = s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=default_bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj.get("Key", "")
                    if key.lower().endswith((".jpg", ".jpeg", ".png")):
                        frame_references.append((default_bucket, key))
        except Exception as error:
            print(f"Could not list video frames from S3 prefix {prefix}: {error}")

    seen = set()
    unique_references = []
    for frame_bucket, frame_key in frame_references:
        reference_id = (frame_bucket, frame_key)
        if frame_bucket and frame_key and reference_id not in seen:
            unique_references.append(reference_id)
            seen.add(reference_id)

    unique_references.sort(key=lambda item: item[1])
    print(f"Collected {len(unique_references)} video frame references for {file_id}.")
    return unique_references


def classify_video_frames(payload):
    tags = {"video_file": 1}
    frame_references = collect_video_frame_references(payload)

    if not frame_references:
        print("No video frames were provided for P3 aggregation.")
        return tags

    for index, (frame_bucket, frame_key) in enumerate(frame_references, start=1):
        try:
            frame_file_id = f"{payload['file_id']}_frame_{index}"
            local_path = download_file(frame_bucket, frame_key, frame_file_id)
            species, confidence = classify_image(local_path)
            tags[species] = tags.get(species, 0) + 1
            print(
                f"Detected {species} in video frame {index} "
                f"({frame_key}) with confidence {confidence}."
            )
        except Exception as error:
            print(f"Failed to classify video frame {frame_key}: {error}")

    return tags


def build_full_url(bucket, object_key):
    return f"https://{bucket}.s3.amazonaws.com/{object_key}"


def save_to_dynamodb(payload, tags):
    file_id = payload["file_id"]

    existing_item = {}
    try:
        existing_result = files_table.get_item(Key={"file_id": file_id})
        existing_item = existing_result.get("Item", {})
    except Exception:
        existing_item = {}

    bucket = payload.get("bucket") or existing_item.get("bucket", "")
    object_key = payload.get("object_key") or existing_item.get("object_key", "")
    s3_uri = payload.get("s3_uri") or existing_item.get("s3_uri", "")
    file_type = payload.get("file_type") or existing_item.get("file_type", "")
    mime_type = payload.get("mime_type") or existing_item.get("mime_type")
    uploaded_at = (
        payload.get("uploaded_at")
        or existing_item.get("uploaded_at")
        or datetime.now(timezone.utc).isoformat()
    )

    thumbnail_key = (
        payload.get("thumbnail_key")
        or existing_item.get("thumbnail_key")
        or ""
    )

    full_url = payload.get("full_url") or existing_item.get("full_url")
    if not full_url and bucket and object_key:
        full_url = build_full_url(bucket, object_key)

    thumbnail_url = payload.get("thumbnail_url") or existing_item.get("thumbnail_url", "")
    if (
        (not thumbnail_url or thumbnail_url.startswith("s3://"))
        and bucket
        and thumbnail_key
    ):
        thumbnail_url = build_full_url(bucket, thumbnail_key)

    secondary_url = (
        payload.get("secondary_url")
        or existing_item.get("secondary_url")
        or existing_item.get("secondary_full_url")
        or ""
    )

    file_item = {
        "file_id": file_id,
        "bucket": bucket,
        "object_key": object_key,
        "s3_uri": s3_uri,
        "file_type": file_type,
        "checksum": payload.get("checksum") or existing_item.get("checksum", ""),
        "checksum_sha256": (
            payload.get("checksum_sha256")
            or existing_item.get("checksum_sha256")
            or payload.get("checksum")
            or existing_item.get("checksum", "")
        ),
        "uploaded_at": uploaded_at,
        "tags": tags,
        "thumbnail_key": thumbnail_key,
        "thumbnail_url": thumbnail_url,
        "full_url": full_url,
        "secondary_url": secondary_url,
        "status": "tagged",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    video_frame_keys = payload.get("video_frame_keys", existing_item.get("video_frame_keys", []))
    video_frame_urls = payload.get("video_frame_urls", existing_item.get("video_frame_urls", []))
    frame_count = payload.get("frame_count", existing_item.get("frame_count"))

    if video_frame_keys:
        file_item["video_frame_keys"] = video_frame_keys

    if video_frame_urls:
        file_item["video_frame_urls"] = video_frame_urls

    if frame_count is not None:
        file_item["frame_count"] = int(frame_count)

    if "file_size" in payload:
        file_item["file_size"] = int(payload["file_size"])
    elif "file_size" in existing_item:
        file_item["file_size"] = existing_item["file_size"]

    if mime_type:
        file_item["mime_type"] = mime_type

    files_table.put_item(Item={**existing_item, **file_item})

    for tag, count in tags.items():
        tag_item = {
            "tag": tag,
            "file_id": file_id,
            "count": int(count),
            "file_type": file_type,
            "thumbnail_key": thumbnail_key,
            "thumbnail_url": thumbnail_url,
            "full_url": full_url,
            "secondary_url": secondary_url,
            "s3_uri": s3_uri,
            "uploaded_at": uploaded_at,
        }

        if mime_type:
            tag_item["mime_type"] = mime_type

        tag_index_table.put_item(Item=tag_item)

    return file_item

def generate_presigned_file_url(bucket, object_key):
    if not bucket or not object_key:
        return ""

    try:
        return s3_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket,
                "Key": object_key,
            },
            ExpiresIn=86400,
        )
    except Exception:
        return ""

def publish_tag_event(payload, tags):
    if not SNS_TOPIC_ARN:
        return

    detected_tags = list(tags.keys())

    if not detected_tags:
        return

    bucket = payload.get("bucket", "")
    object_key = payload.get("object_key", "")
    presigned_url = generate_presigned_file_url(bucket, object_key)

    message = {
        "file_id": payload.get("file_id"),
        "file_type": payload.get("file_type"),
        "mime_type": payload.get("mime_type"),
        "tags": detected_tags,
        "tag_counts": tags,
        "file_url": presigned_url,
        "full_url": payload.get("full_url", ""),
        "thumbnail_url": payload.get("thumbnail_url", ""),
        "secondary_url": payload.get("secondary_url", ""),
        "object_key": object_key,
        "bucket": bucket,
    }

    sns_client.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject="New tagged media uploaded",
        Message=json.dumps(message),
        MessageAttributes={
            "tags": {
                "DataType": "String.Array",
                "StringValue": json.dumps(detected_tags),
            }
        },
    )


def lambda_handler(event, context):
    try:
        payload = normalise_event(event)

        raw_file_type = payload.get("file_type")
        mime_type = payload.get("mime_type")

        if mime_type is None and isinstance(raw_file_type, str) and "/" in raw_file_type:
            mime_type = raw_file_type

        if isinstance(raw_file_type, str) and raw_file_type.startswith("image/"):
            file_type = "image"
        elif isinstance(raw_file_type, str) and raw_file_type.startswith("video/"):
            file_type = "video"
        else:
            file_type = raw_file_type

        payload["file_type"] = file_type

        if mime_type:
            payload["mime_type"] = mime_type


        required_fields = ["file_id", "bucket", "object_key", "file_type"]
        missing_fields = [field for field in required_fields if not payload.get(field)]

        if missing_fields:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "status": "error",
                    "message": f"Missing required fields: {', '.join(missing_fields)}"
                })
            }

        file_id = payload["file_id"]
        if payload.get("checksum_sha256") and payload["file_id"] != payload["checksum_sha256"]:
            print(
                "file_id/checksum_sha256 mismatch; using checksum_sha256 "
                "as canonical file_id"
            )
            payload["file_id"] = payload["checksum_sha256"]

        bucket = payload["bucket"]
        object_key = payload["object_key"]
        file_type = payload["file_type"]

        if file_type not in ["image", "video"]:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "status": "error",
                    "message": "file_type must be either image or video"
                })
            }

        if file_type == "image":
            local_path = download_file(bucket, object_key, file_id)
            species, confidence = classify_image(local_path)
            tags = {species: 1}
            payload["confidence"] = str(confidence)
        else:
            tags = classify_video_frames(payload)

        if payload.get("mode") == "detect_only":
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "status": "success",
                    "mode": "detect_only",
                    "file_id": file_id,
                    "file_type": file_type,
                    "mime_type": payload.get("mime_type"),
                    "tags": tags
                })
            }

        file_item = save_to_dynamodb(payload, tags)
        publish_tag_event(file_item, tags)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": "success",
                "file_id": file_id,
                "file_type": file_type,
                "mime_type": file_item.get("mime_type"),
                "tags": tags,
                "thumbnail_url": file_item.get("thumbnail_url", ""),
                "full_url": file_item.get("full_url", ""),
                "secondary_url": file_item.get("secondary_url", ""),
            })
        }

    except Exception as error:
        return {
            "statusCode": 500,
            "body": json.dumps({
                "status": "error",
                "message": str(error)
            })
        }
