# Aussie EcoLens

> FIT5225 2026 S1 — Assignment 2 (Group 92)
> A multi-cloud serverless wildlife observation platform.

## Overview

Aussie EcoLens lets users upload images and videos, automatically detects Australian wildlife species in the media using pre-trained ML models, and stores tagged results in a cloud database for retrieval. The system is deployed across two cloud providers: **AWS** (primary, hosting all user-facing services) and **Google Cloud Platform** (secondary, providing the notifications gateway and the redundant object-storage mirror).

### Core capabilities

- Browser → S3 direct media upload via presigned PUT URLs, with client-side SHA-256 deduplication checked against a DynamoDB GSI.
- Automatic species tagging through a two-stage ML pipeline (MegaDetector + SpeciesNet) deployed as a container-image Lambda.
- Image thumbnail generation (OpenCV) and 1-fps video frame extraction (FFmpeg).
- RESTful query API: by tags (AND logic with optional minimum counts), by species, by an uploaded reference file, and by thumbnail URL.
- Manual bulk tag editing and file deletion (including thumbnails, frames, DynamoDB rows, tag-index rows, and the GCS mirror).
- Email notifications when newly tagged files match a user's subscribed species tags, delivered via SNS → GCP Cloud Function → Resend.
- AWS Cognito Hosted UI (Authorization Code + PKCE) for authentication; ID-token verification performed at API Gateway.

## Team

| Name | Student ID | Role | Contribution |
|---|---|---|---|
| Yuanhe Wu | 36302414 | P1 — Authentication, API surface, multi-cloud notifications | 28% |
| Guanghui Liu | 34217398 | P2 — File pipeline, GCP storage mirror, delete workflow | 24% |
| Junzhe Zhang | 34682457 | P3 — ML tagging container, query Lambdas, tag editing | 25% |
| Zuyao Wang | 34590706 | P4 — Frontend dashboard, Cognito integration | 23% |

## Architecture

### Multi-cloud topology

```
                ┌─────────── AWS (primary) ───────────────┐
                │                                          │
  Browser ──► Cognito Hosted UI                            │
   (PKCE)      │                                           │
                ▼                                          │
              ID Token                                     │
                │                                          │
                ▼                                          │
  API Gateway (8 routes, Cognito Authorizer, CORS)         │
                │                                          │
        ┌───────┼───────────────────────────┐              │
        ▼       ▼                           ▼              │
   /upload  /query/* /tag/edit /delete   /notifications/   │
   Lambda    Lambdas              Lambda  subscribe Lambda │
        │       │                  │              │        │
        │       ▼                  ▼              │        │
        │   DynamoDB:                            SNS Topic │
        │   - a2_group92_files (PK file_id,                │
        │       GSI checksum_sha256-index)                 │
        │   - a2_group92_tag_index (PK tag, SK file_id)    │
        │       │                                          │
        ▼       │                  ┌── tagging Lambda      │
        S3:     │                  │   (ECR container,     │
        - raw-uploads/             │   MegaDetector +      │
        - thumbnails/              │   SpeciesNet)         │
        - video-frames/            ▲                       │
        - query-files/             │ S3 ObjectCreated      │
                │                  │ trigger               │
                └──► P2 ingest Lambda                      │
                     - SHA-256 fingerprint                 │
                     - Thumbnail (OpenCV)                  │
                     - Video frames (FFmpeg)               │
                     - DDB write + GCS mirror invoke       │
                                                           │
                                  ▼ (mirror)               │
                ┌──── GCP (secondary) ────────────────┐    │
                │                                     │    │
                │   Cloud Run: S3→GCS bridge          │◄───┘
                │   (X-Copy-Secret authenticated)     │
                │   │                                 │
                │   ▼                                 │
                │   GCS bucket (originals,            │
                │   thumbnails, frames mirrored)      │
                │                                     │
                │   Cloud Function (Python 3.12 Gen 2)│◄── SNS HTTPS push
                │   - SubscriptionConfirmation        │    (per-user filtered)
                │   - Tag-event notification          │
                │   - Welcome email                   │
                │   │                                 │
                │   ▼                                 │
                │   Resend API ──► User inbox         │
                └─────────────────────────────────────┘
```

### Tech stack

| Layer | Choice |
|---|---|
| Identity | AWS Cognito (User Pool + Hosted UI, Authorization Code + PKCE) |
| API | AWS API Gateway REST, Cognito Authorizer, CORS preflight + 4xx/5xx Gateway Responses CORS |
| Compute (AWS) | Lambda (Python 3.12 zip) and Lambda (container image via ECR) |
| Compute (GCP) | Cloud Run (S3→GCS bridge) + Cloud Functions Gen 2 (notifications) |
| Storage | AWS S3 (4 prefixes) mirrored to GCS bucket |
| Database | AWS DynamoDB (`a2_group92_files` with `checksum_sha256-index` GSI; `a2_group92_tag_index` composite key) |
| Pub/Sub | AWS SNS Topic with per-subscription String.Array filter policy |
| Email | Resend (HTML email, 3 000/month free tier) |
| ML models | MegaDetector v5a (detection) + SpeciesNet (46-species classification) |
| Media processing | OpenCV (thumbnails), FFmpeg (video frames at 1 fps) |
| Frontend | HTML + vanilla JavaScript (PKCE flow hand-rolled), served locally |

### Deployed endpoints (us-east-1, AWS account `909774767032`)

| Resource | Identifier |
|---|---|
| Cognito User Pool | `us-east-1_BZjxuYgic` |
| Cognito App Client (SPA) | `163h04gavvfl93ap64uclcbjok` |
| Cognito Hosted UI domain | `https://us-east-1bzjxuygic.auth.us-east-1.amazoncognito.com` |
| API Gateway invoke URL (dev) | `https://01bn3v0646.execute-api.us-east-1.amazonaws.com/dev` |
| SNS Topic | `arn:aws:sns:us-east-1:909774767032:a2-group92-tag-events` |
| GCP Cloud Function | `https://a2-group92-notifications-fcjbumcybq-ue.a.run.app` |

### API routes (all Cognito-authorised)

| Method | Path | Owner | Purpose |
|---|---|---|---|
| POST | `/upload` | P1 | Issue presigned S3 PUT URL with SHA-256 dedup |
| POST | `/query/tags` | P3 | Query by tag names with optional minimum counts (AND logic) |
| POST | `/query/species` | P3 | Query by species name |
| POST | `/query/file` | P3 | Synchronously detect species in an uploaded query image and return matches |
| POST | `/query/thumbnail` | P3 | Look up the original media item by thumbnail URL |
| POST | `/tag/edit` | P3 | Add/update or remove tags on existing media |
| POST | `/delete` | P2 | Delete media (originals, thumbnails, frames, DDB rows, tag-index rows, GCS mirror) |
| POST | `/notifications/subscribe` | P1 | Create/refresh a per-user SNS HTTPS subscription |

## Repository structure

```
assignment2/
├── README.md                                  Project overview (this file)
├── .gitignore                                 Ignore rules
├── backend/                                   AWS Lambda source code
│   ├── upload-url/                            P1 — presigned URL + dedup
│   ├── notifications-subscribe/               P1 — SNS HTTPS subscription Lambda
│   ├── file-pipeline/                         P2 — S3 ingest trigger + delete Lambda
│   ├── http-facing-lambdas/                   P3 — query/tag-edit router Lambda
│   ├── person3-tagging-lambda/                P3 — ML tagging container (Dockerfile + handler)
│   └── db/                                    DDB schema reference
├── gcp/                                       Google Cloud Platform source code
│   ├── notifications-cloud-function/          P1 — SNS receiver + Resend dispatcher
│   └── copy-s3-to-gcs/                        P2 — S3 → GCS mirror bridge (Cloud Run)
├── frontend/                                  P4 — single-page web client
│   ├── index.html                             Dashboard markup
│   ├── styles.css                             Themed UI with sidebar background
│   ├── app.js                                 API calls, upload, query logic
│   ├── auth.js                                PKCE login flow (Cognito Hosted UI)
│   ├── callback.html                          OAuth code → token exchange
│   ├── config.js                              Cognito + API endpoint config
│   └── ui_left_column_bg.png                  Aussie wildlife sidebar background
├── docs/                                      Internal interface documents
│   ├── shared_cognito_auth.md                 Single source of truth for Cognito/API IDs
│   ├── api_specification.md                   Endpoint contracts
│   ├── http_facing_lambdas.md                 P3 query Lambda contract
│   ├── person3_api_contract.md                P3 publishing contract
│   ├── person3_day1_setup.md                  P3 environment notes
│   ├── secondary_cloud_storage.md             GCP mirroring design notes
│   └── p2_storage_delete.md                   Delete workflow notes
├── scripts/                                   Deployment helpers
│   ├── create_p2_resources.sh                 P2 ingest pipeline setup
│   ├── create_p2_delete_resources.sh          P2 delete Lambda setup
│   ├── create_person3_resources.sh            P3 container ECR + Lambda setup
│   ├── deploy_gcp_copy_bridge.ps1             Cloud Run deploy script
│   └── p2-s3-cors.json                        S3 CORS policy
├── A2-testsamples/                            Test images grouped by species
├── AussieEcoLense/                            Reference ML pipeline from teaching team
├── test_images/                               Original 25 sample images
└── Aussie_EcoLens_login_background.jpg        Cognito Hosted UI background asset
```

## Running and testing

### Prerequisites

- An AWS Academy Lab session with valid short-lived credentials configured via `aws configure`.
- An active GCP project (for Cloud Run + Cloud Functions Gen 2) with `gcloud` authenticated.
- A Resend account and API key for outbound email.
- Python 3.12 for local ML testing.
- Node + a static file server such as VS Code Live Server (the frontend expects to be served at `http://127.0.0.1:5500/frontend/index.html`).

### Frontend (P4)

```bash
cd assignment2/frontend
# Start VS Code Live Server (or any static server bound to port 5500)
# Then open http://127.0.0.1:5500/frontend/index.html
```

Cognito callback URLs are pinned to `127.0.0.1:5500`; using `localhost` will be rejected.

### AWS Lambda deployment

Each backend folder contains either a `.zip` artifact ready for `aws lambda update-function-code`, or the source from which to build one. The tagging Lambda (P3) is a container image and must be pushed to ECR:

```bash
# Example for upload-url
cd backend/upload-url
zip -r function.zip lambda_function.py
aws lambda update-function-code \
    --function-name a2-group92-upload-url \
    --zip-file fileb://function.zip
```

### GCP Cloud Function deployment

```bash
cd gcp/notifications-cloud-function
gcloud functions deploy a2-group92-notifications \
    --runtime python312 \
    --trigger-http \
    --allow-unauthenticated \
    --entry-point notifications \
    --set-env-vars RESEND_API_KEY=<key>,SENDER_EMAIL="Aussie EcoLens <onboarding@resend.dev>"
```

### Smoke test the end-to-end pipeline

1. Open the frontend at `http://127.0.0.1:5500/frontend/index.html`.
2. Click **Login with Cognito** and sign up / sign in.
3. **Subscribe** an email to a species via the Notification Subscription panel; a welcome email should arrive within seconds.
4. **Upload** an image of one of the 46 species (e.g. a `bos_taurus_*.jpg` from `A2-testsamples/`).
5. Wait 5–10 seconds for the asynchronous tagging pipeline.
6. **Query by Species/Tags** with the matching tag (e.g. `bos_taurus`) and confirm the file appears in Media Results.
7. The subscribed email should also receive a "new observation" notification.

## Deliverables

| Item | Status | Location |
|---|---|---|
| Team report (≤1000 words) | Submitted | `/A2_Group92_Team_Report.pdf` (parent folder) |
| Individual reports (4 × ≤500 words) | Submitted | Each member's Moodle submission |
| Architecture diagram | Included in team report | `FIT5225 A2 Arch Diagram.pdf` |
| Source code | Submitted | This repository |
| GitLab repo (Reporter role for teaching team) | Granted | `https://git.infotech.monash.edu/fit5225a2-group92/assignment2` |
| Zoom demo | Completed | Group 92 demo slot |

## Notes for graders

- All AWS resources live in the AWS account `909774767032` (us-east-1).
- All Lambdas use `LabRole` because the AWS Academy Lab environment does not permit creating custom IAM roles.
- The `X-Copy-Secret` shared secret between the S3→GCS bridge (Cloud Run) and the AWS-side mirroring caller is a pragmatic substitute for GCP Workload Identity Federation, which is not configurable inside Lab constraints.
- The notifications Cloud Function intentionally returns HTTP 200 on most internal failures so that SNS does not endlessly retry transient delivery problems; failures are still logged to Cloud Logging.
- Tag normalisation (`lowercase + underscore-joined whitespace`) is enforced on every ingress hop — frontend, subscribe Lambda, and the tagging Lambda's publish payload — so SNS String.Array filter policies match user-entered tag names regardless of capitalisation or whitespace.

## Acknowledgements

This project used generative AI tools to assist with implementation, debugging, and documentation; full disclosure is given in the AI Acknowledgment section of the team report. All AI-generated outputs were reviewed, tested, and adapted by the team, and all final design decisions remain the responsibility of the four authors.
