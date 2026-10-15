# Person3 API Contract

This document defines the API contract for Person3 query, tag management, delete, and database-related APIs.

Person3 is responsible for:

- ML tagging result storage
- DynamoDB metadata storage
- Tag-based query APIs
- Thumbnail URL lookup
- Query-by-file support
- Manual tag editing
- Database-side delete synchronization

## General Authentication Rule

All protected APIs should expect the following header:

```http
Authorization: Bearer <id_token>
```

Recommended backend integration:

- API Gateway should use Cognito Authorizer.
- API Gateway validates the Cognito token.
- Lambda receives verified user claims from requestContext.authorizer.claims.
- Lambda should use the current user's Cognito sub or username as owner_id.

---

## URL Rule

The API response must return browser-accessible HTTPS URLs or presigned URLs for file_url and thumbnail_url.

The API must not return internal s3:// paths to the frontend.

Reason:

- The frontend needs to display thumbnails in the browser.
- The frontend needs to open original files when users click results.
- Browser image preview cannot use s3:// URLs directly.

DynamoDB may store internal storage references, such as object keys or storage paths. Person3 Query APIs should convert these stored references into HTTPS URLs or presigned URLs before returning results to P4 frontend.

---

## Common Response Fields

API responses should use file_url instead of original_url to match the frontend prototype.

### File Type Rules

The system separates the business-level media category from the MIME content type.

| Field | Meaning | Example |
| --- | --- | --- |
| `file_type` | Business category used by backend and frontend branching logic. Must be either `image` or `video`. | `image` |
| `mime_type` | Original MIME content type from the uploaded file. Used for Content-Type, preview, download, and display metadata. | `image/jpeg` |

`file_type` must not store MIME values such as `image/jpeg` or `video/mp4`. MIME values must be stored in `mime_type`.

Common result item:

```json
{
  "file_id": "abc123",
  "file_url": "https://example.com/original.jpg",
  "thumbnail_url": "https://example.com/thumb.jpg",
  "file_type": "image",
  "mime_type": "image/jpeg",
  "checksum_sha256": "xxx",
  "tags": {
    "kangaroo": 2,
    "koala": 1
  },
  "created_at": "2026-06-01T08:06:49Z",
  "updated_at": "2026-06-01T08:06:49Z"
}
```

If no result is found, return:

```json
{
  "count": 0,
  "results": []
}
```

---

## 1. Query by Tags with Minimum Counts

Endpoint:

```http
POST /query/tags
```

Request:

```json
{
  "tags": {
    "kangaroo": 2,
    "koala": 1
  }
}
```

Logic:

- Each requested tag must exist.
- Counts must be greater than or equal to the requested count.
- Multiple tags use AND logic, not OR logic.
- Example: kangaroo >= 2 AND koala >= 1.

Response:

```json
{
  "count": 1,
  "results": [
    {
      "file_id": "abc123",
      "file_url": "https://example.com/original.jpg",
      "thumbnail_url": "https://example.com/thumb.jpg",
      "file_type": "image",
      "mime_type": "image/jpeg",
      "checksum_sha256": "xxx",
      "tags": {
        "kangaroo": 2,
        "koala": 1
      },
      "created_at": "2026-06-01T08:06:49Z",
      "updated_at": "2026-06-01T08:06:49Z"
    }
  ]
}
```

---

## 2. Query by Species

Endpoint:

```http
POST /query/species
```

Request:

```json
{
  "species": "kangaroo"
}
```

Logic:

- Return all images and videos containing at least one kangaroo.
- This is equivalent to a tag query where kangaroo >= 1.

Response:

```json
{
  "count": 1,
  "results": [
    {
      "file_id": "abc123",
      "file_url": "https://example.com/original.jpg",
      "thumbnail_url": "https://example.com/thumb.jpg",
      "file_type": "image",
      "mime_type": "image/jpeg",
      "checksum_sha256": "xxx",
      "tags": {
        "kangaroo": 2
      },
      "created_at": "2026-06-01T08:06:49Z",
      "updated_at": "2026-06-01T08:06:49Z"
    }
  ]
}
```

---

## 3. Thumbnail URL Lookup

Endpoint:

```http
GET /query/thumbnail?thumbnail_url=<thumbnail_url>
```

Logic:

- User provides a thumbnail URL.
- Backend returns the corresponding full-size file URL.
- This is mainly used when the frontend user clicks a thumbnail preview.
- Both thumbnail_url and file_url in the response must be browser-accessible HTTPS URLs or presigned URLs.

Response:

```json
{
  "thumbnail_url": "https://example.com/thumb.jpg",
  "file_url": "https://example.com/original.jpg"
}
```

If not found:

```json
{
  "thumbnail_url": "https://example.com/thumb.jpg",
  "file_url": null
}
```

---

## 4. Query by Uploaded File

Endpoint:

```http
POST /query/file
```

Request:

- multipart/form-data
- field name: file

Logic:

- User uploads a file only for query purposes.
- Backend runs ML tagging on this temporary file.
- The temporary query file must not be permanently stored.
- The detected tag set is used to search existing database records.
- Return files that contain the same detected species tags.
- Returned file_url and thumbnail_url must be browser-accessible HTTPS URLs or presigned URLs.

Response:

```json
{
  "detected_tags": {
    "kangaroo": 1,
    "koala": 1
  },
  "count": 1,
  "results": [
    {
      "file_id": "abc123",
      "file_url": "https://example.com/original.jpg",
      "thumbnail_url": "https://example.com/thumb.jpg",
      "file_type": "image",
      "mime_type": "image/jpeg",
      "checksum_sha256": "xxx",
      "tags": {
        "kangaroo": 2,
        "koala": 1
      },
      "created_at": "2026-06-01T08:06:49Z",
      "updated_at": "2026-06-01T08:06:49Z"
    }
  ]
}
```

---

## 5. Bulk Tag Edit

Endpoint:

```http
POST /tags/edit
```

Request:

```json
{
  "urls": [
    "https://example.com/original.jpg"
  ],
  "tags": {
    "dingo": 1
  },
  "operation": 1
}
```

Operation:

- 1 means add or update tags.
- 0 means remove tags.
- If a tag requested for deletion does not exist, ignore it.

Logic:

- Support bulk editing for multiple file URLs.
- Update tags in a2_group92_files.
- Update related records in a2_group92_tag_index.
- The two tables must stay consistent.
- Input URLs are expected to be browser-accessible file URLs.
- Backend may need to map the provided file_url back to the stored file record.

Response:

```json
{
  "message": "Tags updated successfully",
  "updated_count": 1
}
```

---

## 6. Delete Files

Endpoint:

```http
POST /delete
```

Request:

```json
{
  "urls": [
    "https://example.com/original.jpg"
  ]
}
```

Logic:

Delete must remove:

- Original file from cloud storage
- Thumbnail file from cloud storage
- Metadata record from a2_group92_files
- Related tag records from a2_group92_tag_index

Person3 is responsible for database-side delete synchronization. Storage-side deletion will be integrated with Person2 storage pipeline.

Input URLs are expected to be browser-accessible file URLs. Backend may need to map the provided file_url back to the stored file record and internal storage reference.

Response:

```json
{
  "message": "Files deleted successfully",
  "deleted_count": 1
}
```

---

## 7. Integration Notes for P2 and P4

### Tagging Lambda Input Payload

The Tagging Lambda is invoked by the Upload Lambda after upload and deduplication are completed.

Example payload:

```json
{
  "file_id": "file_abc123",
  "bucket": "a2-group92-media",
  "object_key": "uploads/file_abc123.jpg",
  "file_type": "image",
  "mime_type": "image/jpeg"
}
```

Required fields:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `file_id` | string | Yes | Unique file ID generated by the upload flow and used as the primary file identifier |
| `bucket` | string | Yes | Source S3 bucket name |
| `object_key` | string | Yes | S3 object key of the uploaded media file |
| `file_type` | string | Yes | Business category of the media file. Must be either `image` or `video` |
| `mime_type` | string | Yes | MIME content type of the uploaded file, such as `image/jpeg`, `image/png`, or `video/mp4` |

### P2 Storage Pipeline Should Provide

When a file is uploaded and processed, P2 should provide or trigger the following values for Person3 database insertion:

```json
{
  "file_id": "abc123",
  "owner_id": "cognito-user-sub-001",
  "file_type": "image",
  "mime_type": "image/jpeg",
  "original_url": "raw/file_001.jpg",
  "thumbnail_url": "thumbnails/file_001.jpg",
  "checksum_sha256": "xxx",
  "created_at": "2026-06-01T08:06:49Z"
}
```

P2 may provide internal S3 object keys or storage paths to Person3.

Person3 Query APIs should convert stored object references into browser-accessible HTTPS URLs or presigned URLs before returning results to P4 frontend.

### P4 Frontend Should Use

P4 frontend should call Person3 APIs with:

```http
Authorization: Bearer <id_token>
```

The frontend should expect:

- file_url as a browser-accessible HTTPS URL or presigned URL
- thumbnail_url as a browser-accessible HTTPS URL or presigned URL
- no s3:// internal paths in API responses
