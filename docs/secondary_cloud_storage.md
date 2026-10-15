# Secondary Cloud Storage - GCP

## Design

Person 2 uses AWS S3 as the primary storage and Google Cloud Storage as the
secondary cloud storage.

The AWS upload Lambda does not store a GCP service account JSON key. Instead,
it generates short-lived S3 presigned URLs and calls a GCP Cloud Run function.
Cloud Run downloads each file from the presigned URL and writes it to the GCS
bucket using its own Google-managed service identity.

Flow:

```text
AWS S3 upload
  -> P2 AWS Lambda processes the file
  -> P2 Lambda generates S3 presigned URL
  -> P2 Lambda calls GCP Cloud Run copy bridge
  -> Cloud Run uploads the object to GCS
  -> P2 Lambda stores secondary GCS metadata in DynamoDB
```

## GCP Resources

- Project ID: `fit5225-a2-group92`
- Region: `us-east1`
- GCS bucket: `a2-group92-secondary-storage`
- Cloud Run service: `copy-s3-to-gcs`
- Function entry point: `copy_s3_to_gcs`
- Cloud Run service account:
  `fit5225-gcs-uploader@fit5225-a2-group92.iam.gserviceaccount.com`

## Deploy Cloud Run

Run these commands in PowerShell from the repository root.

```powershell
gcloud config set project fit5225-a2-group92
gcloud config set run/region us-east1

$env:COPY_SECRET = "<team secret>"
.\scripts\deploy_gcp_copy_bridge.ps1
```

The script prints the Cloud Run service URL. Use that URL as
`GCP_COPY_ENDPOINT` for the AWS Lambda environment.

## Deploy P2 Lambda With Secondary Storage Enabled

Run the P2 deployment script with these environment variables set:

```bash
export ENABLE_SECONDARY_STORAGE=true
export SECONDARY_PROVIDER=gcp
export GCS_BUCKET=a2-group92-secondary-storage
export GCP_COPY_ENDPOINT=https://copy-s3-to-gcs-737094674625.us-east1.run.app
export GCP_COPY_SECRET="<team secret>"

bash scripts/create_p2_resources.sh
```

Do not commit or screenshot the `COPY_SECRET` / `GCP_COPY_SECRET` value.

## DynamoDB Fields Added By P2

The P2 Lambda stores these fields in `a2_group92_files`:

- `secondary_provider`
- `secondary_bucket`
- `secondary_object_key`
- `secondary_full_url`
- `secondary_thumbnail_key`
- `secondary_thumbnail_url`
- `secondary_frame_keys`
- `secondary_frame_urls`
- `secondary_frames_prefix`
- `secondary_copy_status`

## Delete Flow

The P2 storage delete Lambda calls the same Cloud Run bridge with
`operation=delete`. Cloud Run deletes the requested GCS object keys and frame
prefixes using its Google-managed service account, while the AWS Lambda deletes
the matching S3 objects and DynamoDB metadata.
