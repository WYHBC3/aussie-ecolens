import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4
from urllib.parse import urlparse

from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field


# =========================
# Basic path settings
# =========================

# BASE_DIR is the project root directory, which is the fit5225_mvp folder.
BASE_DIR = Path(__file__).resolve().parent.parent

# Uploaded original images are stored in uploads/.
UPLOAD_DIR = BASE_DIR / "uploads"

# Generated thumbnails are stored in thumbnails/.
THUMBNAIL_DIR = BASE_DIR / "thumbnails"

# Temporary query files are stored here only during POST /query/file handling.
QUERY_TEMP_DIR = BASE_DIR / "work" / "query_files"

# SQLite database file.
DB_PATH = BASE_DIR / "database.sqlite3"

# Create folders automatically if they do not exist.
UPLOAD_DIR.mkdir(exist_ok=True)
THUMBNAIL_DIR.mkdir(exist_ok=True)
QUERY_TEMP_DIR.mkdir(parents=True, exist_ok=True)


app = FastAPI(title="FIT5225 A2 Local Wildlife Tagging MVP")

# Allow the local frontend prototype to call the FastAPI backend during demos.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "file://",
        "null",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Make local files accessible through /uploads/xxx and /thumbnails/xxx.
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/thumbnails", StaticFiles(directory=THUMBNAIL_DIR), name="thumbnails")


# =========================
# Request body models
# =========================


class EditTagsRequest(BaseModel):
    urls: Optional[List[str]] = Field(
        default=None,
        description="List of original image URLs, for example ['/uploads/example.jpg'].",
    )

    file_id: Optional[str] = Field(
        default=None,
        description="Optional compatibility field for editing a single file by file_id.",
    )

    tags: Dict[str, int] = Field(
        ...,
        description="Tags to add, update, or remove.",
        json_schema_extra={"example": {"dingo": 1}},
    )

    operation: int = Field(
        ...,
        description="Use 1 to add or update tags. Use 0 to remove tags.",
        json_schema_extra={"example": 1},
    )

    class Config:
        json_schema_extra = {
            "example": {
                "urls": ["/uploads/xxx.jpg", "/uploads/yyy.jpg"],
                "tags": {"dingo": 1},
                "operation": 1,
            }
        }


class DeleteRequest(BaseModel):
    urls: Optional[List[str]] = Field(
        default=None,
        description="List of original image URLs to delete.",
    )

    file_id: Optional[str] = Field(
        default=None,
        description="Optional compatibility field for deleting a single file by file_id.",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "urls": ["/uploads/xxx.jpg", "/uploads/yyy.jpg"],
            }
        }


# =========================
# Database helper functions
# =========================


def get_db_connection() -> sqlite3.Connection:
    """Create a SQLite connection and return rows that behave like dictionaries."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the database table if it does not already exist."""
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS media (
                file_id TEXT PRIMARY KEY,
                file_url TEXT NOT NULL,
                thumbnail_url TEXT NOT NULL,
                file_type TEXT NOT NULL,
                mime_type TEXT,
                checksum TEXT NOT NULL UNIQUE,
                tags TEXT NOT NULL,
                upload_time TEXT NOT NULL
            )
            """
        )
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(media)").fetchall()
        }
        if "mime_type" not in columns:
            conn.execute("ALTER TABLE media ADD COLUMN mime_type TEXT")


def row_to_dict(row: sqlite3.Row) -> dict:
    """Convert one database row into a dictionary for API responses."""
    data = dict(row)
    data["tags"] = json.loads(data["tags"])
    return data


def to_contract_media(record: dict) -> dict:
    """Add Person 3 contract field names while keeping old local MVP fields."""
    created_at = record.get("created_at") or record.get("upload_time")
    updated_at = record.get("updated_at") or record.get("upload_time") or created_at
    mime_type = record.get("mime_type") or infer_mime_type(record.get("file_type"))

    return {
        **record,
        "file_type": get_business_file_type(mime_type),
        "mime_type": mime_type,
        "checksum_sha256": record.get("checksum_sha256") or record.get("checksum"),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def infer_mime_type(value: Optional[str]) -> str:
    """Infer a MIME type from old local rows where file_type stored Content-Type."""
    if value and "/" in value:
        return value
    return "application/octet-stream"


def get_business_file_type(mime_type: Optional[str]) -> str:
    """Map a MIME type to the business-level file_type category."""
    if mime_type and mime_type.startswith("image/"):
        return "image"
    if mime_type and mime_type.startswith("video/"):
        return "video"
    return "unknown"


@app.on_event("startup")
def on_startup() -> None:
    # Prepare the database when FastAPI starts.
    init_db()


# =========================
# Image and tag helper functions
# =========================


def calculate_sha256(file_path: Path) -> str:
    """Calculate the SHA-256 checksum used for duplicate upload detection."""
    sha256 = hashlib.sha256()

    # Read the file in chunks to avoid loading large files into memory.
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def create_thumbnail(source_path: Path, thumbnail_path: Path) -> None:
    """Generate a thumbnail while preserving the original image aspect ratio."""
    with Image.open(source_path) as image:
        # thumbnail() preserves aspect ratio, so the image will not be stretched.
        image.thumbnail((256, 256))

        # Some PNG files use RGBA mode, which cannot be saved directly as JPEG.
        # Converting to RGB keeps this local MVP simple.
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")

        image.save(thumbnail_path, format="JPEG", quality=85)


def mock_ml_tagging(_: Path) -> Dict[str, int]:
    """Mock ML tagging function. Replace this later with a real ML model."""
    return {"koala": 1, "wombat": 2}


def find_by_checksum(checksum: str) -> Optional[dict]:
    """Find an uploaded file by checksum."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM media WHERE checksum = ?",
            (checksum,),
        ).fetchone()

    return row_to_dict(row) if row else None


def find_by_file_id(file_id: str) -> Optional[dict]:
    """Find an uploaded file by file_id."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM media WHERE file_id = ?",
            (file_id,),
        ).fetchone()

    return row_to_dict(row) if row else None


def find_by_file_url(file_url: str) -> Optional[dict]:
    """Find an uploaded file by its original image URL."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM media WHERE file_url = ?",
            (file_url,),
        ).fetchone()

    return row_to_dict(row) if row else None


def normalize_url_path(url: str) -> str:
    """Extract path from a full URL and remove query parameters."""
    parsed = urlparse(url)
    path = parsed.path if parsed.scheme else url

    if not path.startswith("/"):
        path = "/" + path

    return path


def find_by_thumbnail_url(thumbnail_url: str) -> Optional[dict]:
    """Find an uploaded file by its thumbnail URL."""
    normalized_path = normalize_url_path(thumbnail_url)

    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM media
            WHERE thumbnail_url = ?
               OR thumbnail_url = ?
               OR thumbnail_url LIKE ?
            """,
            (
                thumbnail_url,
                normalized_path,
                f"%{normalized_path}",
            ),
        ).fetchone()

    return row_to_dict(row) if row else None


def get_records_from_request(urls: Optional[List[str]], file_id: Optional[str]) -> List[dict]:
    """Resolve bulk URLs or a compatibility file_id into per-item records."""
    records: List[dict] = []

    if urls:
        for url in urls:
            records.append({"url": url, "record": find_by_file_url(url)})
        return records

    if file_id:
        record = find_by_file_id(file_id)
        records.append({"url": record["file_url"] if record else file_id, "record": record})
        return records

    raise HTTPException(
        status_code=400,
        detail="Invalid request. Provide either urls or file_id.",
    )


def parse_query_tags(payload: Dict[str, Any]) -> Dict[str, int]:
    """Support both {'tags': {...}} and the assignment format {'koala': 1}."""
    if "tags" in payload:
        tags = payload["tags"]
        if not isinstance(tags, dict):
            raise HTTPException(status_code=400, detail="Invalid request. tags must be an object.")
        return tags

    return payload


def search_media_by_tags(required_tags: Dict[str, int]) -> List[dict]:
    """Search stored media using minimum-count AND logic."""
    results: List[dict] = []

    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM media ORDER BY upload_time DESC").fetchall()

    for row in rows:
        item = row_to_dict(row)
        item_tags = item["tags"]

        matched = all(
            item_tags.get(tag_name, 0) >= required_count
            for tag_name, required_count in required_tags.items()
        )

        if matched:
            results.append(to_contract_media(item))

    return results


# =========================
# API endpoints
# =========================


@app.post(
    "/upload",
    responses={
        200: {
            "description": "Image uploaded or duplicate detected.",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Upload successful.",
                        "duplicate": False,
                        "data": {
                            "file_id": "xxxx",
                            "file_url": "/uploads/xxxx.jpg",
                            "thumbnail_url": "/thumbnails/xxxx.jpg",
                            "file_type": "image",
                            "mime_type": "image/jpeg",
                            "checksum_sha256": "xxxx",
                            "checksum": "xxxx",
                            "tags": {"koala": 1, "wombat": 2},
                            "created_at": "2026-05-31T00:00:00+00:00",
                            "updated_at": "2026-05-31T00:00:00+00:00",
                            "upload_time": "2026-05-31T00:00:00+00:00",
                        },
                    }
                }
            },
        }
    },
)
async def upload_image(file: UploadFile = File(...)) -> dict:
    """
    Upload an image file.

    The server saves the original file locally, calculates a SHA-256 checksum,
    prevents duplicate uploads, generates a thumbnail, runs mock ML tagging,
    and stores metadata in SQLite.
    """
    mime_type = file.content_type or "application/octet-stream"
    file_type = get_business_file_type(mime_type)

    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload an image file.")

    file_id = str(uuid4())
    original_suffix = Path(file.filename or "").suffix.lower() or ".jpg"
    upload_filename = f"{file_id}{original_suffix}"
    thumbnail_filename = f"{file_id}.jpg"

    upload_path = UPLOAD_DIR / upload_filename
    thumbnail_path = THUMBNAIL_DIR / thumbnail_filename

    # Save the uploaded file first, so we can calculate checksum and create a thumbnail.
    with upload_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # Verify that the uploaded content is a real image.
        with Image.open(upload_path) as image:
            image.verify()

        checksum = calculate_sha256(upload_path)
        existing = find_by_checksum(checksum)
        if existing:
            # Delete the temporary duplicate file because the original is already stored.
            upload_path.unlink(missing_ok=True)
            return {
                "message": "Duplicate file detected. The file was not saved again.",
                "duplicate": True,
                "data": to_contract_media(existing),
            }

        create_thumbnail(upload_path, thumbnail_path)
        tags = mock_ml_tagging(upload_path)
        upload_time = datetime.now(timezone.utc).isoformat()

        record = {
            "file_id": file_id,
            "file_url": f"/uploads/{upload_filename}",
            "thumbnail_url": f"/thumbnails/{thumbnail_filename}",
            "file_type": file_type,
            "mime_type": mime_type,
            "checksum": checksum,
            "checksum_sha256": checksum,
            "tags": tags,
            "created_at": upload_time,
            "updated_at": upload_time,
            "upload_time": upload_time,
        }

        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO media (
                    file_id, file_url, thumbnail_url, file_type,
                    mime_type, checksum, tags, upload_time
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["file_id"],
                    record["file_url"],
                    record["thumbnail_url"],
                    record["file_type"],
                    record["mime_type"],
                    record["checksum"],
                    json.dumps(record["tags"]),
                    record["upload_time"],
                ),
            )

        return {
            "message": "Upload successful.",
            "duplicate": False,
            "data": to_contract_media(record),
        }

    except HTTPException:
        raise
    except Exception as exc:
        # Clean up partial files if image processing fails.
        upload_path.unlink(missing_ok=True)
        thumbnail_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Image processing failed: {exc}") from exc


@app.post(
    "/query/tags",
    responses={
        200: {
            "description": "Matching media records.",
            "content": {
                "application/json": {
                    "example": {
                        "count": 1,
                        "results": [
                            {
                                "file_id": "xxxx",
                                "file_url": "/uploads/xxxx.jpg",
                                "thumbnail_url": "/thumbnails/xxxx.jpg",
                                "file_type": "image",
                                "mime_type": "image/jpeg",
                                "checksum_sha256": "xxxx",
                                "checksum": "xxxx",
                                "tags": {"koala": 1, "wombat": 2},
                                "created_at": "2026-05-31T00:00:00+00:00",
                                "updated_at": "2026-05-31T00:00:00+00:00",
                                "upload_time": "2026-05-31T00:00:00+00:00",
                            }
                        ],
                    }
                }
            },
        }
    },
)
def query_by_tags(
    request: Dict[str, Any] = Body(
        ...,
        examples=[{"koala": 1, "wombat": 2}],
        description=(
            "Tags to query. Supports either {'koala': 1} or "
            "{'tags': {'koala': 1}}. Multiple tags use AND logic."
        ),
    )
) -> dict:
    """
    Query images by tags.

    Multiple tags use AND logic, and each stored tag count must be greater than
    or equal to the requested minimum count.
    """
    required_tags = parse_query_tags(request)
    results = search_media_by_tags(required_tags)
    return {"count": len(results), "results": results}


@app.post(
    "/query/file",
    responses={
        200: {
            "description": "Detected query tags and matching media records.",
            "content": {
                "application/json": {
                    "example": {
                        "query_tags": {"koala": 1, "wombat": 2},
                        "count": 1,
                        "results": [
                            {
                                "file_id": "xxxx",
                                "file_url": "/uploads/xxxx.jpg",
                                "thumbnail_url": "/thumbnails/xxxx.jpg",
                                "file_type": "image",
                                "mime_type": "image/jpeg",
                                "checksum_sha256": "xxxx",
                                "tags": {"koala": 1, "wombat": 2},
                                "created_at": "2026-05-31T00:00:00+00:00",
                                "updated_at": "2026-05-31T00:00:00+00:00",
                            }
                        ],
                    }
                }
            },
        }
    },
)
async def query_by_file(file: UploadFile = File(...)) -> dict:
    """
    Query existing media by uploading a temporary file.

    The temporary query file is used only for mock ML tagging and is not inserted
    into SQLite or permanently stored in uploads/ or thumbnails/.
    """
    mime_type = file.content_type or "application/octet-stream"
    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload an image file.")

    file_suffix = Path(file.filename or "").suffix.lower() or ".jpg"
    temp_path = QUERY_TEMP_DIR / f"{uuid4()}{file_suffix}"

    try:
        with temp_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        with Image.open(temp_path) as image:
            image.verify()

        query_tags = mock_ml_tagging(temp_path)
        results = search_media_by_tags(query_tags)
        return {
            "query_tags": query_tags,
            "count": len(results),
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Query file processing failed: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)


@app.get(
    "/query/thumbnail",
    responses={
        200: {
            "description": "Original full-size image URL for the requested thumbnail URL.",
            "content": {
                "application/json": {
                    "example": {
                        "thumbnail_url": "/thumbnails/xxxx.jpg",
                        "file_url": "/uploads/xxxx.jpg",
                        "file_id": "xxxx",
                        "file_type": "image",
                        "mime_type": "image/jpeg",
                        "checksum_sha256": "xxxx",
                        "tags": {"koala": 1, "wombat": 2},
                        "created_at": "2026-05-31T00:00:00+00:00",
                        "updated_at": "2026-05-31T00:00:00+00:00",
                    }
                }
            },
        }
    },
)
def get_thumbnail(
    thumbnail_url: str = Query(..., description="Thumbnail URL, for example /thumbnails/xxx.jpg"),
) -> dict:
    """Return the original full-size image URL for a given thumbnail URL."""
    existing = find_by_thumbnail_url(thumbnail_url)

    if not existing:
        raise HTTPException(status_code=404, detail="Thumbnail URL not found.")

    return to_contract_media(existing)


@app.post(
    "/tags/edit",
    responses={
        200: {
            "description": "Per-URL tag edit results.",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Tags updated successfully.",
                        "results": [
                            {
                                "url": "/uploads/xxxx.jpg",
                                "file_id": "xxxx",
                                "file_url": "/uploads/xxxx.jpg",
                                "thumbnail_url": "/thumbnails/xxxx.jpg",
                                "file_type": "image",
                                "mime_type": "image/jpeg",
                                "checksum_sha256": "xxxx",
                                "status": "success",
                                "tags": {"koala": 1, "wombat": 2, "dingo": 1},
                                "created_at": "2026-05-31T00:00:00+00:00",
                                "updated_at": "2026-05-31T00:00:00+00:00",
                            }
                        ],
                    }
                }
            },
        }
    },
)
def edit_tags(request: EditTagsRequest) -> dict:
    """
    Manually add, update, or remove tags for one or more uploaded files.

    The assignment format uses urls, tags, and operation. operation=1 adds or
    updates tags. operation=0 removes tags.
    """
    if request.operation not in (0, 1):
        raise HTTPException(
            status_code=400,
            detail="Invalid operation. Use 1 to add or update tags, or 0 to remove tags.",
        )

    items = get_records_from_request(request.urls, request.file_id)
    results: List[dict] = []

    for item in items:
        url = item["url"]
        existing = item["record"]
        if not existing:
            results.append({"url": url, "status": "not found", "message": "File not found."})
            continue

        updated_tags = dict(existing["tags"])

        if request.operation == 1:
            # Existing tags are updated to the provided count instead of being added
            # arithmetically. This keeps manual edits explicit and predictable.
            updated_tags.update(request.tags)
        else:
            for tag_name in request.tags:
                # Removing a missing tag is harmless and should not fail the request.
                updated_tags.pop(tag_name, None)

        with get_db_connection() as conn:
            conn.execute(
                "UPDATE media SET tags = ? WHERE file_id = ?",
                (json.dumps(updated_tags), existing["file_id"]),
            )

        updated_record = to_contract_media({**existing, "tags": updated_tags})
        results.append(
            {
                **updated_record,
                "url": existing["file_url"],
                "status": "success",
            }
        )

    return {"message": "Tags updated successfully.", "results": results}


@app.post(
    "/delete",
    responses={
        200: {
            "description": "Per-URL delete results.",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Delete operation completed.",
                        "results": [
                            {
                                "url": "/uploads/xxxx.jpg",
                                "file_id": "xxxx",
                                "file_url": "/uploads/xxxx.jpg",
                                "thumbnail_url": "/thumbnails/xxxx.jpg",
                                "file_type": "image",
                                "mime_type": "image/jpeg",
                                "checksum_sha256": "xxxx",
                                "tags": {"koala": 1, "wombat": 2},
                                "created_at": "2026-05-31T00:00:00+00:00",
                                "updated_at": "2026-05-31T00:00:00+00:00",
                                "status": "success",
                                "message": "File deleted successfully.",
                            }
                        ],
                    }
                }
            },
        }
    },
)
def delete_file(request: DeleteRequest) -> dict:
    """
    Delete original files, thumbnail files, and database records.

    The assignment format uses a list of original image URLs. file_id is kept
    only as a compatibility option for the earlier local prototype.
    """
    items = get_records_from_request(request.urls, request.file_id)
    results: List[dict] = []

    for item in items:
        url = item["url"]
        existing = item["record"]
        if not existing:
            results.append({"url": url, "status": "not found", "message": "File not found."})
            continue

        upload_path = BASE_DIR / existing["file_url"].lstrip("/")
        thumbnail_path = BASE_DIR / existing["thumbnail_url"].lstrip("/")

        upload_path.unlink(missing_ok=True)
        thumbnail_path.unlink(missing_ok=True)

        with get_db_connection() as conn:
            conn.execute(
                "DELETE FROM media WHERE file_id = ?",
                (existing["file_id"],),
            )

        deleted_record = to_contract_media(existing)
        results.append(
            {
                **deleted_record,
                "url": existing["file_url"],
                "status": "success",
                "message": "File deleted successfully.",
            }
        )

    return {"message": "Delete operation completed.", "results": results}
