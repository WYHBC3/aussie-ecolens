# API Specification for Local FastAPI MVP

## 1. Overview

This document describes the tested API endpoints in the local FastAPI MVP for the FIT5225 Assignment 2 project.

The current MVP is a local backend prototype. It supports image upload, checksum-based duplicate detection, thumbnail generation, mock ML tagging, SQLite metadata storage, tag-based queries, thumbnail lookup, bulk tag editing, and file deletion.

This API specification is intended to support later migration to the final multi-cloud architecture, where these local endpoints can be adapted to API Gateway, Lambda functions, cloud storage, and cloud database services.

Media response fields use these meanings:

* `file_type`: business-level category, one of `image`, `video`, or `unknown`
* `mime_type`: actual MIME type / Content-Type, such as `image/jpeg`, `image/png`, or `video/mp4`

## 2. Current MVP Limitations

The current MVP has the following limitations:

* Local storage only
* SQLite database only
* Mock ML tagging only
* No AWS Cognito authentication yet
* No API Gateway yet
* No cloud storage yet
* No serverless trigger yet
* No real ML model integration yet
* No tag-based notification yet
* No production frontend UI yet

## 3. Base URL

For local testing, the base URL is:

```text
http://127.0.0.1:8000
```

Swagger documentation is available at:

```text
http://127.0.0.1:8000/docs
```

---

# 4. API Endpoints

## 4.1 Upload Media

### Endpoint

```http
POST /upload
```

### Purpose

Uploads an image or video file. The upload flow supports `image/*` and `video/*` media types.

### Request Type

```text
multipart/form-data
```

### Request Field

| Field | Type | Required | Description                                |
| ----- | ---- | -------- | ------------------------------------------ |
| file  | File | Yes      | The image or video media file to upload    |

### Success Response Example

```json
{
  "message": "Upload successful.",
  "duplicate": false,
  "data": {
    "file_id": "6daf86e3-5192-4cd8-bc04-f0e29547b0f7",
    "file_url": "/uploads/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg",
    "thumbnail_url": "/thumbnails/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg",
    "file_type": "image",
    "mime_type": "image/jpeg",
    "checksum": "5a291580d6f276ed05ea4e78629130d77ee3c198a7d9b284a9b7738be7056da3",
    "tags": {
      "koala": 1,
      "wombat": 2
    },
    "upload_time": "2026-05-31T07:44:53.555492+00:00"
  }
}
```

### Duplicate Upload Response Example

```json
{
  "message": "Duplicate file detected. The file was not saved again.",
  "duplicate": true,
  "data": {
    "file_id": "6daf86e3-5192-4cd8-bc04-f0e29547b0f7",
    "file_url": "/uploads/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg",
    "thumbnail_url": "/thumbnails/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg",
    "file_type": "image",
    "mime_type": "image/jpeg",
    "checksum": "5a291580d6f276ed05ea4e78629130d77ee3c198a7d9b284a9b7738be7056da3",
    "tags": {
      "koala": 1,
      "wombat": 2
    },
    "upload_time": "2026-05-31T07:44:53.555492+00:00"
  }
}
```

### Tested Status

Tested successfully.

---

## 4.2 Query Files by Tags and Minimum Counts

### Endpoint

```http
POST /query/tags
```

### Purpose

Finds files that contain all requested tags and satisfy the required minimum count for each tag.

This endpoint uses logical AND matching. For example, the query below only returns files that contain at least one koala and at least two wombats.

### Request Example

```json
{
  "koala": 1,
  "wombat": 2
}
```

### Success Response Example

```json
{
  "count": 1,
  "results": [
    {
      "file_id": "6daf86e3-5192-4cd8-bc04-f0e29547b0f7",
      "file_url": "/uploads/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg",
      "thumbnail_url": "/thumbnails/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg",
      "file_type": "image",
      "mime_type": "image/jpeg",
      "checksum": "5a291580d6f276ed05ea4e78629130d77ee3c198a7d9b284a9b7738be7056da3",
      "tags": {
        "koala": 1,
        "wombat": 2
      },
      "upload_time": "2026-05-31T07:44:53.555492+00:00"
    }
  ]
}
```

### No Result Example

```json
{
  "count": 0,
  "results": []
}
```

### Tested Cases

| Test Case           | Request                     | Expected Result       | Status |
| ------------------- | --------------------------- | --------------------- | ------ |
| Single tag query    | `{"koala": 1}`              | Returns uploaded file | Passed |
| Multiple tag query  | `{"koala": 1, "wombat": 2}` | Returns uploaded file | Passed |
| Minimum count query | `{"koala": 2}`              | Returns empty results | Passed |
| AND logic query     | `{"koala": 1, "dingo": 1}`  | Returns empty results | Passed |

### Tested Status

Tested successfully.

---

## 4.3 Query Full-Size Image by Thumbnail URL

### Endpoint

```http
GET /query/thumbnail
```

### Purpose

Maps a thumbnail URL to its corresponding full-size image URL.

This supports the UI design where thumbnails can be displayed first, and the full-size image URL can be retrieved when the user clicks a thumbnail.

### Query Parameter

| Parameter     | Type   | Required | Description                  |
| ------------- | ------ | -------- | ---------------------------- |
| thumbnail_url | String | Yes      | The thumbnail URL to look up |

### Request Example

```text
GET /query/thumbnail?thumbnail_url=/thumbnails/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg
```

### Success Response Example

```json
{
  "thumbnail_url": "/thumbnails/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg",
  "file_url": "/uploads/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg"
}
```

### Error Response Example

```json
{
  "detail": "Thumbnail URL not found."
}
```

### Tested Status

Tested successfully.

---

## 4.4 Bulk Add or Remove Tags

### Endpoint

```http
POST /tags/edit
```

### Purpose

Adds or removes tags for one or more files using file URLs.

This endpoint supports the assignment requirement for manual bulk tag editing. The `operation` field controls whether tags are added or removed:

* `operation = 1`: add or update tags
* `operation = 0`: remove tags

If a tag requested for deletion does not exist, the system ignores it and does not return an error.

### Request Example: Add Tag

```json
{
  "urls": [
    "/uploads/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg"
  ],
  "tags": {
    "dingo": 1
  },
  "operation": 1
}
```

### Success Response Example: Add Tag

```json
{
  "message": "Tags updated successfully.",
  "results": [
    {
      "url": "/uploads/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg",
      "file_id": "6daf86e3-5192-4cd8-bc04-f0e29547b0f7",
      "status": "success",
      "tags": {
        "koala": 1,
        "wombat": 2,
        "dingo": 1
      }
    }
  ]
}
```

### Request Example: Remove Tag

```json
{
  "urls": [
    "/uploads/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg"
  ],
  "tags": {
    "dingo": 1
  },
  "operation": 0
}
```

### Success Response Example: Remove Tag

```json
{
  "message": "Tags updated successfully.",
  "results": [
    {
      "url": "/uploads/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg",
      "file_id": "6daf86e3-5192-4cd8-bc04-f0e29547b0f7",
      "status": "success",
      "tags": {
        "koala": 1,
        "wombat": 2
      }
    }
  ]
}
```

### Tested Cases

| Test Case                           | Expected Result                            | Status |
| ----------------------------------- | ------------------------------------------ | ------ |
| Add `dingo: 1`                      | Tags become `koala`, `wombat`, and `dingo` | Passed |
| Query `{"dingo": 1}` after adding   | Returns uploaded file                      | Passed |
| Remove `dingo: 1`                   | Tags become `koala` and `wombat`           | Passed |
| Query `{"dingo": 1}` after removing | Returns empty results                      | Passed |

### Tested Status

Tested successfully.

---

## 4.5 Delete Files

### Endpoint

```http
POST /delete
```

### Purpose

Deletes one or more files from local storage and removes the corresponding metadata from the SQLite database.

For image files, the endpoint deletes both:

* the original uploaded image
* the generated thumbnail
* the database record

### Request Example: Delete by URLs

```json
{
  "urls": [
    "/uploads/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg",
    "/uploads/another-file.jpg"
  ]
}
```

### Request Example: Delete by File IDs

```json
{
  "file_ids": [
    "6daf86e3-5192-4cd8-bc04-f0e29547b0f7",
    "another-file-id"
  ]
}
```

### Success Response Example

```json
{
  "message": "Delete completed.",
  "results": [
    {
      "url": "/uploads/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg",
      "status": "deleted"
    }
  ]
}
```

### Verification Steps

After deletion, the following checks should pass:

1. Querying `{"koala": 1}` returns:

```json
{
  "count": 0,
  "results": []
}
```

2. Opening the original image URL returns `404 Not Found`.

```text
http://127.0.0.1:8000/uploads/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg
```

3. Opening the thumbnail URL returns `404 Not Found`.

```text
http://127.0.0.1:8000/thumbnails/6daf86e3-5192-4cd8-bc04-f0e29547b0f7.jpg
```

### Tested Status

Tested successfully.

---

## 4.6 Query by Uploaded File

### Endpoint

```http
POST /query/file
```

### Purpose

The user uploads a temporary query file. The local mock backend detects tags from the uploaded file with the mock ML tagging function and searches for database records that match the detected tags.

The query file is temporary. It is not saved in `uploads/`, does not create a thumbnail, and is not inserted into SQLite metadata.

### Request Type

```text
multipart/form-data
```

### Request Field

| Field | Type | Required | Description                                                   |
| ----- | ---- | -------- | ------------------------------------------------------------- |
| file  | File | Yes      | Temporary image file used only for mock tag detection and matching |

### Success Response Example

```json
{
  "query_tags": {
    "koala": 1,
    "wombat": 2
  },
  "count": 1,
  "results": [
    {
      "file_id": "example-file-id",
      "file_url": "/uploads/example.jpg",
      "thumbnail_url": "/thumbnails/example.jpg",
      "file_type": "image",
      "mime_type": "image/jpeg",
      "checksum_sha256": "example-checksum",
      "tags": {
        "koala": 1,
        "wombat": 2
      },
      "created_at": "2026-05-31T07:44:53.555492+00:00",
      "updated_at": "2026-05-31T07:44:53.555492+00:00"
    }
  ]
}
```

### Current Status

Implemented in the current local MVP with mock ML tagging only.

---

## 4.7 Subscribe to Tag Notifications

### Endpoint

```http
POST /notifications/subscribe
```

### Purpose

Subscribes the user to email notifications for selected tags. When new media matches the selected tags, the notification pipeline can send an email to the subscribed address.

### Request Type

```text
application/json
```

### Request Example

```json
{
  "tags": ["koala", "wombat"],
  "email": "user@x.com"
}
```

### Current Status

Implemented by the notification backend endpoint. The frontend calls this endpoint with the existing Authorization header helper when a Cognito ID token is available.

---

# 5. Mapping to Final Cloud Architecture

The current local FastAPI endpoints can be mapped to the final cloud architecture as follows:

| Local MVP Endpoint     | Final Cloud Component                         | Notes                                                             |
| ---------------------- | --------------------------------------------- | ----------------------------------------------------------------- |
| `POST /upload`         | Upload Pipeline Lambda / API Gateway          | Replace local storage with S3 and trigger processing functions    |
| `POST /query/tags`     | Query & Management Lambda                     | Query DynamoDB using tag index and AND logic                      |
| `GET /query/thumbnail` | Query & Management Lambda                     | Return full-size S3 URL from thumbnail URL                        |
| `POST /tags/edit`      | Query & Management Lambda                     | Update tags in DynamoDB                                           |
| `POST /delete`         | Query & Management Lambda                     | Delete S3 objects and DynamoDB records                            |
| `POST /query/file`     | Query & Management Lambda + Tagging Container | Detect tags from temporary query file and search matching records |
| `POST /notifications/subscribe` | Notification Lambda / SNS             | Subscribe an email address to selected tag notifications          |

---

# 6. Notes for Frontend UI

The frontend UI should call these APIs to support:

* Image upload
* Duplicate upload feedback
* Tag-based search form
* Result display with thumbnail previews
* Full-size image lookup by thumbnail URL
* Bulk tag add/remove
* File deletion
* Email notification subscription by tags

In the final system, the frontend should call the deployed API Gateway URL instead of the local FastAPI URL.

---

# 7. Notes for Future Cloud Migration

To migrate this MVP to the final assignment architecture, the following changes are required:

1. Replace local storage with S3 buckets.
2. Replace SQLite with DynamoDB.
3. Replace mock ML tagging with the real ML model.
4. Add video frame extraction at 1 frame per second.
5. Add API Gateway routing.
6. Add CORS configuration.
7. Add Cognito Authorizer for protected API access.
8. Add tag-based email notification.
9. Connect the frontend UI to the deployed cloud APIs.
