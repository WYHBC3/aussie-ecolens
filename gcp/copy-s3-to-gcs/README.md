# GCP Copy Bridge

This Cloud Run function copies one AWS S3 object into the secondary Google Cloud
Storage bucket and deletes GCS objects for the storage cleanup flow. AWS Lambda
sends a short-lived S3 presigned URL for copy operations, so no GCP service
account JSON key is needed inside AWS.

## Environment

Required Cloud Run environment variables:

```text
GCS_BUCKET=a2-group92-secondary-storage
COPY_SECRET=<set locally, do not commit>
SIGNED_URL_EXPIRES_SECONDS=900
```

Copied objects stay private in GCS. The bridge returns a temporary signed GCS
URL in the `url` and `signed_url` response fields so the frontend can open the
mirrored object without making the bucket public.

If Cloud Run cannot sign URLs with its default credentials, set
`GCP_SIGNING_SERVICE_ACCOUNT` to the Cloud Run service account email and grant
that service account the `Service Account Token Creator` role.

## Deploy

From the repository root:

```powershell
$env:COPY_SECRET = "<team secret>"
.\scripts\deploy_gcp_copy_bridge.ps1
```

The deployed service URL should be configured in the P2 AWS Lambda environment
as `GCP_COPY_ENDPOINT`.
