# P2 Storage Delete

Person 2 provides a storage-side delete Lambda named `p2-storage-delete`.

The Lambda can be invoked by the final `/delete` API implementation or tested
directly with AWS CLI. It accepts `file_ids`, `urls`, `file_id`, or `url`.

## What It Deletes

- AWS S3 original object
- AWS S3 generated thumbnail
- AWS S3 extracted video frames
- GCS secondary original object
- GCS secondary thumbnail
- GCS secondary video frames
- DynamoDB record in `a2_group92_files`
- Related tag index rows in `a2_group92_tag_index`

GCS deletion uses the existing Cloud Run bridge. The same `COPY_SECRET` is sent
as `X-Copy-Secret`; no GCP service account JSON key is stored in AWS.

## Deploy

Run from the repository root:

```bash
export GCP_COPY_ENDPOINT=https://copy-s3-to-gcs-737094674625.us-east1.run.app
export GCP_COPY_SECRET="<team secret>"

bash scripts/create_p2_delete_resources.sh
```

## Test

Invoke by file ID:

```bash
aws lambda invoke \
  --function-name p2-storage-delete \
  --payload '{"file_ids":["<sha256-file-id>"]}' \
  --cli-binary-format raw-in-base64-out \
  --region us-east-1 \
  delete-output.json
```

Then verify:

```bash
aws s3 ls s3://a2-group92-p2-media-909774767032/uploads/
aws s3 ls s3://a2-group92-p2-media-909774767032/thumbnails/
aws s3 ls s3://a2-group92-p2-media-909774767032/video-frames/<sha256-file-id>/

gcloud storage ls gs://a2-group92-secondary-storage/uploads/
gcloud storage ls gs://a2-group92-secondary-storage/thumbnails/
gcloud storage ls gs://a2-group92-secondary-storage/frames/<sha256-file-id>/

aws dynamodb get-item \
  --table-name a2_group92_files \
  --key '{"file_id":{"S":"<sha256-file-id>"}}' \
  --region us-east-1
```

The DynamoDB `get-item` command should return no `Item` after deletion.
