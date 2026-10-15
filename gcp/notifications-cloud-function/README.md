# notifications-cloud-function

GCP Cloud Function (Python 3.12, Gen 2, HTTP trigger) that receives SNS
HTTPS push messages from AWS and sends rich-HTML emails to end users via
the Resend API.

This is the GCP half of the Aussie EcoLens multi-cloud notifications
pipeline:

```
P3 Tagging Lambda ──publish──> SNS Topic (AWS)
                                 │
                                 │ HTTPS POST (one per filtered subscription)
                                 ↓
                          this Cloud Function (GCP)
                                 │
                                 │ Resend API
                                 ↓
                          end user's inbox
```

## Files

| Path | Purpose |
|---|---|
| `main.py` | Function handler. |
| `requirements.txt` | Pinned Python deps. |
| `deploy.sh` | One-shot `gcloud functions deploy` script. |
| `tests/sample_notification.json` | SNS Notification envelope for local testing. |
| `tests/sample_subscription_confirmation.json` | SNS SubscriptionConfirmation envelope. |

## Local development

```bash
cd gcp/notifications-cloud-function
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export RESEND_API_KEY='re_...your_key...'
export SENDER_EMAIL='Aussie EcoLens <onboarding@resend.dev>'

functions-framework --target=notifications --debug --port=8080
```

In a second terminal, simulate an SNS Notification with a curl POST. The
recipient email is passed as a query string param (`?email=...`) because
SNS preserves the endpoint URL's query string when delivering messages,
which lets us bake the user identity into the subscription URL at the
time `/notifications/subscribe` creates the subscription.

```bash
curl -X POST "http://localhost:8080?email=wyhbc3@gmail.com" \
  -H "Content-Type: text/plain" \
  -H "x-amz-sns-message-type: Notification" \
  --data-binary "@tests/sample_notification.json"
```

Expected: `OK` (200) and a real email arriving at the configured Resend
account inbox within ~30 seconds.

To exercise the subscription handshake path:

```bash
curl -X POST "http://localhost:8080" \
  -H "Content-Type: text/plain" \
  -H "x-amz-sns-message-type: SubscriptionConfirmation" \
  --data-binary "@tests/sample_subscription_confirmation.json"
```

(The fake `SubscribeURL` will return non-200, so the response will be
500 — that is expected for a local test.)

## Deployment

Prerequisites:
- `gcloud` CLI authenticated against a project with billing enabled.
- The following APIs enabled on the project:
  - `cloudfunctions.googleapis.com`
  - `cloudbuild.googleapis.com`
  - `run.googleapis.com`
  - `eventarc.googleapis.com`

```bash
export RESEND_API_KEY='re_...your_key...'
bash deploy.sh
```

The script prints the Cloud Run trigger URL on success; this is the URL
that `/notifications/subscribe` should hand to SNS as the HTTPS endpoint.

## Wiring into AWS SNS

After deployment, the `/notifications/subscribe` Lambda needs to switch
its `sns.subscribe(...)` call from `Protocol="email"` to:

```python
sns.subscribe(
    TopicArn=TOPIC_ARN,
    Protocol="https",
    Endpoint=f"{CLOUD_FUNCTION_URL}?email={quote(user_email, safe='')}",
    Attributes={"FilterPolicy": json.dumps(filter_policy)},
    ReturnSubscriptionArn=True,
)
```

The first request SNS sends to the Cloud Function URL after subscription
will be a `SubscriptionConfirmation`, which this function auto-confirms
by GET'ing the supplied `SubscribeURL`. Subsequent messages will be
`Notification` envelopes that trigger the email send.

## Environment variables (production)

| Name | Required | Description |
|---|---|---|
| `RESEND_API_KEY` | yes | Resend API key with at least "Sending access". |
| `SENDER_EMAIL` | no | RFC-5322 `From` header. Default: `Aussie EcoLens <onboarding@resend.dev>`. |

## Security notes

This prototype performs only a lightweight SNS envelope sanity check
(`TopicArn` and `Type` present). For production hardening the
`_verify_sns_message` function should be extended to verify the SNS
message `Signature` against the cert at `SigningCertURL`, per
[AWS docs](https://docs.aws.amazon.com/sns/latest/dg/sns-verify-signature-of-message.html).

The recipient email is currently passed as a URL query string parameter,
which is acceptable while the Cloud Function URL is unlisted and the
Resend account is restricted to sending only to the verified-account
address. If a custom sender domain is later verified with Resend, the
recipient email should be HMAC-signed or replaced with an opaque
subscription token to avoid recipient enumeration via URL logs.
