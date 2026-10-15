$ErrorActionPreference = "Stop"

$ProjectId = if ($env:GCP_PROJECT_ID) { $env:GCP_PROJECT_ID } else { "fit5225-a2-group92" }
$Region = if ($env:GCP_REGION) { $env:GCP_REGION } else { "us-east1" }
$ServiceName = if ($env:GCP_COPY_SERVICE) { $env:GCP_COPY_SERVICE } else { "copy-s3-to-gcs" }
$Bucket = if ($env:GCS_BUCKET) { $env:GCS_BUCKET } else { "a2-group92-secondary-storage" }
$SignedUrlExpires = if ($env:SIGNED_URL_EXPIRES_SECONDS) { $env:SIGNED_URL_EXPIRES_SECONDS } else { "900" }
$ServiceAccount = if ($env:GCP_COPY_SERVICE_ACCOUNT) {
  $env:GCP_COPY_SERVICE_ACCOUNT
} else {
  "fit5225-gcs-uploader@fit5225-a2-group92.iam.gserviceaccount.com"
}

if (-not $env:COPY_SECRET) {
  throw "Set COPY_SECRET in this terminal before deploying. Do not commit it."
}

$SourceDir = Join-Path $PSScriptRoot "..\gcp\copy-s3-to-gcs"
$EnvVars = "GCS_BUCKET=$Bucket,COPY_SECRET=$env:COPY_SECRET,SIGNED_URL_EXPIRES_SECONDS=$SignedUrlExpires"

if ($env:GCP_SIGNING_SERVICE_ACCOUNT) {
  $EnvVars = "$EnvVars,GCP_SIGNING_SERVICE_ACCOUNT=$env:GCP_SIGNING_SERVICE_ACCOUNT"
}

gcloud config set project $ProjectId
gcloud config set run/region $Region

gcloud run deploy $ServiceName `
  --source $SourceDir `
  --region $Region `
  --function copy_s3_to_gcs `
  --base-image python312 `
  --service-account $ServiceAccount `
  --set-env-vars $EnvVars `
  --allow-unauthenticated

gcloud run services describe $ServiceName `
  --region $Region `
  --format "value(status.url)"
