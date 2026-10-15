# Shared Cognito Authentication Information

> Owner: Yuanhe Wu. All values verified on D1 (2026-05-31). For any change, please ping P1 first so this file stays the single source of truth.

## Region and Account

- Region: `us-east-1`
- AWS Account ID hosting Cognito: `909774767032`

## User Pool

- User Pool ID: `us-east-1_BZjxuYgic`
- User Pool ARN: `arn:aws:cognito-idp:us-east-1:909774767032:userpool/us-east-1_BZjxuYgic`
- Issuer: `https://cognito-idp.us-east-1.amazonaws.com/us-east-1_BZjxuYgic`

Required attributes for sign-up (cannot be changed without recreating the pool):
- `email`
- `given_name`
- `family_name`

## App Client

- App Client Name: `a2-group92-spa`
- App Type: Single-page application (SPA)
- Client ID: `163h04gavvfl93ap64uclcbjok`
- Client Secret: none (SPA mode — must not be added; PKCE replaces it)

OAuth configuration:
- Grant type: Authorization code grant (PKCE)
- Scopes: `openid email profile`

Allowed callback URLs (both registered to support either entry point):
- `http://127.0.0.1:5500/frontend/callback.html` — currently used by P4 frontend
- `http://127.0.0.1:5500/frontend/index.html` — backup / future use

Allowed sign-out URL:
- `http://127.0.0.1:5500/frontend/index.html`

> ⚠️ Cognito does strict-string match. `127.0.0.1` and `localhost` are NOT interchangeable; the browser must use `127.0.0.1` exactly.

## Hosted UI

- Cognito Domain: `https://us-east-1bzjxuygic.auth.us-east-1.amazoncognito.com`
- Login URL pattern (replace `<REDIRECT>` with one of the allowed callback URLs):
  ```
  https://us-east-1bzjxuygic.auth.us-east-1.amazoncognito.com/login
    ?client_id=163h04gavvfl93ap64uclcbjok
    &response_type=code
    &scope=openid+email+profile
    &redirect_uri=<REDIRECT>
    &code_challenge=<PKCE_CHALLENGE>
    &code_challenge_method=S256
  ```

## API Gateway

- API name: `a2-group92-api`
- API ID: `01bn3v0646`
- Region: `us-east-1`
- Invoke URL (dev stage): `https://01bn3v0646.execute-api.us-east-1.amazonaws.com/dev`
- Authorizer: `cognito-authorizer` (Cognito User Pool authorizer, token source = `Authorization` header)
- Test endpoint: `GET /hello` (mock; returns user claims for verification)

### How to call protected endpoints

```bash
curl -H "Authorization: Bearer <id_token>" \
  https://01bn3v0646.execute-api.us-east-1.amazonaws.com/dev/<resource>
```

Lambdas (when added by P2/P3) will read user claims from:
`event.requestContext.authorizer.claims`

## SNS — Tag-based Notifications

- Topic name: `a2-group92-tag-events`
- Topic ARN: `arn:aws:sns:us-east-1:909774767032:a2-group92-tag-events`
- Type: Standard
- Region: `us-east-1`

### How the Tagging Lambda publishes (current, since D3)

After writing tags to DynamoDB, the Tagging Lambda publishes one message
per file with a single `tags` MessageAttribute of type **String.Array**
carrying every detected species. SNS String.Array filter policies give
OR semantics across a subscription's watched-tag list, which is what we
want — "notify me if a new file contains koala **or** wombat".

```python
sns.publish(
    TopicArn="arn:aws:sns:us-east-1:909774767032:a2-group92-tag-events",
    Message=json.dumps({
        "file_id": file_id,
        "file_url": presigned_url_to_file,   # presigned to survive private bucket
        "tags": detected_tags,                # e.g. ["koala", "wombat"]
    }),
    MessageAttributes={
        "tags": {
            "DataType": "String.Array",
            "StringValue": json.dumps(detected_tags),
        },
    },
)
```

> The earlier per-species `tag_<species>=1` String pattern was abandoned
> on D3 because filter policies over multiple String attributes use AND
> semantics across the keys — "only deliver if tag_koala=1 AND
> tag_wombat=1" — which is not what users want.

### How users subscribe (current, since D5)

`POST /notifications/subscribe` creates one SNS HTTPS subscription per
user. The endpoint URL points at the GCP notifications Cloud Function
and carries the recipient email as a URL-encoded query string parameter:

```
Endpoint = https://<cloud-function-url>?email=<urlencoded user email>
```

SNS preserves the query string when delivering each notification, so the
Cloud Function knows where to send the email without needing a second
"subscribers" DynamoDB table. The subscription's `FilterPolicy` is
`{"tags": [<lowercased watched tags>...]}` — String.Array semantics —
so SNS only forwards messages whose `tags` attribute overlaps the
user's watchlist.

End delivery is GCP-side: see `gcp/notifications-cloud-function/`.

## Token Verification Endpoints

- JWKS URL: `https://cognito-idp.us-east-1.amazonaws.com/us-east-1_BZjxuYgic/.well-known/jwks.json`
- OpenID configuration: `https://cognito-idp.us-east-1.amazonaws.com/us-east-1_BZjxuYgic/.well-known/openid-configuration`

## Backend Plan

**API Gateway uses a Cognito Authorizer.** Lambda functions behind API Gateway do NOT need to verify JWTs themselves. Verified claims are forwarded by API Gateway and can be read inside Lambda as:

```python
def lambda_handler(event, context):
    claims = event["requestContext"]["authorizer"]["claims"]
    owner_id = claims["sub"]         # Cognito user UUID
    email    = claims["email"]
    given    = claims.get("given_name")
    family   = claims.get("family_name")
    ...
```

The `sub` value is the canonical owner identifier and should be stored in DynamoDB `owner_id` columns.

For services that do NOT sit behind API Gateway (e.g. the GCP Cloud Function that receives SNS HTTPS pushes), JWT validation must be done manually using the JWKS URL above. The validator must check:
- Signature against the JWKS public keys
- `iss` equals the Issuer URL
- `aud` equals the App Client ID (`163h04gavvfl93ap64uclcbjok`)
- `exp` is in the future

## Quick Reference Per Role

### P2 — File Pipeline Lambdas
- Lambdas triggered by S3 events (upload, thumbnail, frame extract) run server-to-server and do NOT see the user JWT directly. Take the `owner_id` from the metadata that the upload-handling Lambda persisted in DynamoDB or from S3 object tags.
- The HTTP-facing upload endpoint (if any) sits behind API Gateway and gets `claims` as shown above.

### P3 — Tagging, Query, Tag Management, Delete Lambdas
- All HTTP-facing endpoints sit behind API Gateway with the Cognito Authorizer. Read claims from `event["requestContext"]["authorizer"]["claims"]`.
- Use `claims["sub"]` as `owner_id` for both `a2_group92_files` and `a2_group92_tag_index` writes.
- Query, edit, and delete endpoints should filter by `owner_id` to enforce user isolation.

### P4 — Frontend (SPA, served by VSCode Live Server at `127.0.0.1:5500`)
- Use Authorization Code + PKCE. Recommended library: `oidc-client-ts`.
- Send `Authorization: Bearer <id_token>` on every API call. Use `id_token`, not `access_token`, because our Authorizer is configured for ID tokens (so that custom attributes like `given_name`, `family_name` are available to Lambdas).
- During local development, the FastAPI mock backend runs at `localhost:8000` and must reply with the appropriate CORS headers for origin `http://127.0.0.1:5500`.

### GCP Cloud Function (Notifications)
- Verify JWT manually using `python-jose` or `PyJWT` against the JWKS URL above.
- Issuer and audience checks are mandatory.

## Test Account (team-shared)

> Maintained out-of-band in the team's shared doc (not committed to git). If you need a confirmed test account quickly, ping P1.

## Change Log

- 2026-06-01 (D1) — Initial Cognito pool created, Hosted UI verified end-to-end.
- 2026-06-02 (D2) — Callback URLs finalized to `callback.html` + `index.html`; added per-role quick reference; clarified Authorizer responsibility split.
- 2026-06-03 (D3) — P3 Tagging Lambda deployed as ECR container image. SNS Topic `a2-group92-tag-events` created with String.Array filter-policy convention so a single `tags` attribute carries the per-image species list. (Switched from earlier `tag_<species>=1` String pattern to fix the AND-vs-OR semantics across multi-tag subscriptions.)
- 2026-06-04 (D4) — All 7 user-facing API Gateway routes deployed under stage `dev`: `POST /query/tags`, `POST /query/species`, `GET /query/thumbnail`, `POST /query/file`, `POST /tags/edit`, `POST /delete`, `POST /notifications/subscribe`. All sit behind `cognito-authorizer`. End-to-end token + 401/200 sanity checks pass on every route.
- 2026-06-05 (D5) — Several integration milestones and one configuration regression:
  - `POST /upload` added: presigned-URL Lambda (`a2-group92-upload-url`) lets the SPA frontend `PUT` files directly to S3, which then fires P2's existing ObjectCreated pipeline.
  - P2 secondary-storage Cloud Run bridge verified end-to-end (S3 → GCS).
  - P3 Tagging container had a missing `onnx2torch` dependency causing silent handler failures; P3 rebuilt + redeployed, then tags began landing in DDB correctly.
  - **Regression**: earlier in the day, two CLI calls of `aws cognito-idp update-user-pool-client --explicit-auth-flows ...` were used to enable `ALLOW_USER_PASSWORD_AUTH` for backend testing. Because `UpdateUserPoolClient` has PUT semantics, these calls also wiped `CallbackURLs`, `LogoutURLs`, `AllowedOAuthFlows`, `AllowedOAuthScopes`, `SupportedIdentityProviders`, and `AllowedOAuthFlowsUserPoolClient`. Hosted-UI login started returning `redirect_mismatch`. Configuration was fully restored from the AWS console (see ⚠️ note below).
  - `/query/thumbnail` Authorization had reverted to AWS_IAM and was reset to `cognito-authorizer` + redeployed to `dev`.
  - `/delete` route was **temporarily removed from API Gateway** after P2's delete Lambda was found to delete the wrong DynamoDB row on URL inputs that don't match `s3://` or `*.s3.amazonaws.com` patterns (the URL-matcher's `secondary_keys` fallback evaluated `None in [None, ...]` as truthy). Will be re-attached once P2 patches the Lambda.
  - GCP Cloud Function `gcp/notifications-cloud-function/` written and verified locally with `functions-framework`; deployment blocked overnight on GCP project access.
  - `/notifications/subscribe` Lambda code switched from `Protocol="email"` to `Protocol="https"` pointed at the Cloud Function URL, with the recipient email URL-encoded into the endpoint's query string. Deploy is deferred until the Cloud Function is live.

> ⚠️ **CLI gotcha**: `aws cognito-idp update-user-pool-client` has PUT semantics — every field not explicitly passed gets reset to its default. Always use the AWS console for multi-field changes, or pass the full current configuration when scripting.
