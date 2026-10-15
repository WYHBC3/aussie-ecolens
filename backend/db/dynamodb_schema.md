# DynamoDB Schema

This document defines the DynamoDB schema for Person3: ML tagging, database storage, and query APIs.

## 1. Table: a2_group92_files

This table stores one metadata record for each uploaded media file.

### Primary Key

- Partition key: file_id
- Type: string

### Attributes

| Field | Type | Description |
| --- | --- | --- |
| file_id | string | Unique ID for the uploaded file |
| owner_id | string | Cognito user sub or username of the uploader |
| file_type | string | Business category of the media file. Must be either `image` or `video`. This field is used by backend and frontend logic to decide whether the result is handled as an image or a video. |
| mime_type | string | Original MIME content type of the uploaded file, such as `image/jpeg`, `image/png`, or `video/mp4`. This field is used for Content-Type, preview, download, and display metadata. |
| original_url | string | Internal storage reference for the original uploaded file. This may be a bucket/key, storage path, or internal URL. If it is an internal s3:// path, it must not be directly returned to the frontend. |
| thumbnail_url | string | Internal storage reference for the generated thumbnail. API responses must convert this into a browser-accessible HTTPS URL or presigned URL before returning it to the frontend. |
| checksum_sha256 | string | SHA-256 checksum used for duplicate detection |
| tags | map<string, number> | Detected or manually edited species tags and counts |
| model_version | string | ML model version used for tagging |
| created_at | string | Upload timestamp in ISO 8601 format |
| updated_at | string | Last update timestamp in ISO 8601 format |

### Example Item

```json
{
  "file_id": "file_abc123",
  "user_id": "user_001",
  "file_type": "image",
  "mime_type": "image/jpeg",
  "bucket": "a2-group92-media",
  "object_key": "uploads/file_abc123.jpg",
  "file_url": "https://...",
  "thumbnail_url": "https://...",
  "tags": {
    "kangaroo": 2,
    "koala": 1
  },
  "checksum": "sha256_hash",
  "created_at": "2026-06-03T10:30:00Z"
}
```

### Planned GSI for Deduplication

To support checksum-based duplicate detection efficiently, the following GSI is planned:

- GSI name: checksum_sha256-index
- Partition key: checksum_sha256
- Type: string

Without this index, duplicate checking would require scanning the whole table, which is inefficient.

---

## 2. Table: a2_group92_tag_index

This table is an inverted index from tag to file. It supports tag queries, minimum count filtering, and AND logic for multiple tags.

### Primary Key

- Partition key: tag
- Sort key: file_id

### Attributes

| Field | Type | Description |
| --- | --- | --- |
| tag | string | Species tag name |
| file_id | string | File ID that contains this tag |
| owner_id | string | Cognito user sub or username of the uploader |
| count | number | Number of detected or manually assigned objects for this tag |
| file_type | string | Business category of the media file. Must be either `image` or `video`. |
| mime_type | string | Original MIME content type of the uploaded file, such as `image/jpeg`, `image/png`, or `video/mp4`. |
| original_url | string | Internal storage reference for the original uploaded file |
| thumbnail_url | string | Internal storage reference for the generated thumbnail |

### Example Item

```json
{
  "tag": "kangaroo",
  "file_id": "file_001",
  "owner_id": "cognito-user-sub-001",
  "count": 2,
  "file_type": "image",
  "mime_type": "image/jpeg",
  "original_url": "raw/file_001.jpg",
  "thumbnail_url": "thumbnails/file_001.jpg"
}
```

### Query Logic

For a query such as:

```json
{
  "kangaroo": 2,
  "koala": 1
}
```

The backend should:

1. Query a2_group92_tag_index where tag = kangaroo and count >= 2.
2. Query a2_group92_tag_index where tag = koala and count >= 1.
3. Intersect the returned file_id sets.
4. Return only files that satisfy all requested tags.

This means multiple tags use AND logic, not OR logic.

### User Isolation

For the final integrated version, query, delete, and tag edit operations should only affect files owned by the current authenticated user.

Recommended approach:

- Read owner_id from Cognito claims.
- Store owner_id in both a2_group92_files and a2_group92_tag_index.
- Filter query and update operations by owner_id.

A future optimization is to use a composite partition key such as owner_id#tag for the tag index if user isolation becomes difficult with the current design.

---

## 3. URL Handling Rule

DynamoDB may store internal storage references such as:

- bucket name
- object key
- internal storage path
- internal s3:// path

However, API responses must return browser-accessible URLs.

The frontend should receive:

- file_url: HTTPS URL or presigned URL for the original file
- thumbnail_url: HTTPS URL or presigned URL for the thumbnail

The API must not return internal s3:// paths to the frontend because browsers cannot display images from s3:// URLs directly.

---

## 4. API Field Mapping

The database may store original_url internally.

For API responses, Person3 should return file_url to match the P4 frontend prototype.

Mapping:

| Database field | API response field |
| --- | --- |
| original_url | file_url |
| thumbnail_url | thumbnail_url |
| checksum_sha256 | checksum_sha256 |
| created_at | created_at |
| updated_at | updated_at |
| tags | tags |

Important:

- Database storage fields can be internal references.
- API response fields must be browser-accessible HTTPS URLs or presigned URLs.
- P4 frontend should never receive s3:// paths.
