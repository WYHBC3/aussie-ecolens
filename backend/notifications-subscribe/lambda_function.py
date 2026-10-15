"""
notifications-subscribe
=======================

Creates a per-user SNS HTTPS subscription that points at the GCP
notifications Cloud Function. Each subscription embeds the user's
recipient email in the endpoint URL's query string so the Cloud
Function knows where to send the email when SNS delivers a
filtered notification.

Architecture
------------
    POST /notifications/subscribe (Cognito-authenticated)
        body: {"tags": ["koala", "wombat"], "email": "..."}
              email defaults to the Cognito claim if absent.
                │
                ↓
        sns.subscribe(
            TopicArn=a2-group92-tag-events,
            Protocol="https",
            Endpoint="<CLOUD_FUNCTION_URL>?email=<urlencoded user email>",
            FilterPolicy={"tags": [...lowercased tags...]},
        )

SNS will then HTTPS-POST a SubscriptionConfirmation to the Cloud
Function, which auto-GETs the SubscribeURL to confirm. After that,
any matching tag-event message will be POSTed to the same URL —
which still carries ``?email=...`` — and the Cloud Function will
hand it off to Resend.

Environment variables
---------------------
TOPIC_ARN            ARN of the SNS tag-events topic.
CLOUD_FUNCTION_URL   HTTPS URL of the GCP notifications Cloud Function,
                     e.g. https://us-east1-myproject.cloudfunctions.net/a2-group92-notifications
"""

import json
import os
import urllib.request
from urllib.parse import quote

import boto3
from botocore.exceptions import ClientError


sns = boto3.client("sns")

TOPIC_ARN = os.environ["TOPIC_ARN"]
CLOUD_FUNCTION_URL = os.environ.get("CLOUD_FUNCTION_URL", "").rstrip("/")


def _send_welcome_email(email: str, tags: list) -> None:
    """Fire-and-forget POST to the GCP Cloud Function welcome endpoint so
    the subscriber gets immediate confirmation. Network/Resend failures
    are logged but never block the user-facing subscribe response — the
    SNS subscription itself was already created successfully by the time
    we get here.
    """
    if not CLOUD_FUNCTION_URL:
        return

    payload = json.dumps({"email": email, "tags": tags}).encode("utf-8")
    request = urllib.request.Request(
        CLOUD_FUNCTION_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-aussie-message-type": "welcome",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            print(f"Welcome email triggered for {email}: status={resp.status}")
    except Exception as exc:
        print(f"Welcome email request failed for {email}: {exc}")


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body),
    }


def _build_endpoint_url(email: str) -> str:
    """Cloud Function URL with the recipient email baked into the query string.

    URL-encoding is mandatory: `quote(..., safe="")` ensures the `@` and any
    `+` in the email are percent-escaped so SNS forwards the URL verbatim.
    """
    return f"{CLOUD_FUNCTION_URL}?email={quote(email, safe='')}"


def _unsubscribe_existing(email: str) -> int:
    """Remove any prior HTTPS subscription that this email already has on
    the topic, to keep subscription state idempotent.

    Matching rule: same TopicArn, Protocol=https, endpoint contains
    ``email=<urlencoded email>`` (we don't pin the Cloud Function URL
    prefix in case it changes between deploys).

    Returns the number of subscriptions removed.
    """
    removed = 0
    needle = f"email={quote(email, safe='')}"
    next_token = None
    while True:
        kwargs = {"TopicArn": TOPIC_ARN}
        if next_token:
            kwargs["NextToken"] = next_token
        resp = sns.list_subscriptions_by_topic(**kwargs)
        for sub in resp.get("Subscriptions", []):
            if sub.get("Protocol") != "https":
                continue
            endpoint = sub.get("Endpoint", "")
            if needle not in endpoint:
                continue
            arn = sub.get("SubscriptionArn")
            # PendingConfirmation subscriptions don't have a real ARN
            # we can unsubscribe by — they expire on their own after
            # ~3 days and are harmless.
            if arn and arn != "PendingConfirmation":
                sns.unsubscribe(SubscriptionArn=arn)
                removed += 1
        next_token = resp.get("NextToken")
        if not next_token:
            break
    return removed


def lambda_handler(event, context):
    # CORS preflight
    if event.get("httpMethod") == "OPTIONS":
        return _response(200, {})

    if not CLOUD_FUNCTION_URL:
        return _response(
            500,
            {
                "error": (
                    "CLOUD_FUNCTION_URL env var is not configured on this Lambda. "
                    "Set it to the deployed notifications Cloud Function HTTPS URL."
                )
            },
        )

    # Parse body
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON in request body"})

    email = body.get("email")
    tags = body.get("tags", [])

    # Fall back to Cognito claims if email not in body
    if not email:
        try:
            claims = event["requestContext"]["authorizer"]["claims"]
            email = claims.get("email")
        except KeyError:
            pass

    if not email:
        return _response(400, {"error": "email is required"})

    if not isinstance(tags, list) or not tags:
        return _response(400, {"error": "tags must be a non-empty list"})

    # SNS String.Array filter policy: OR semantics across the listed tags.
    # Normalize each tag to match the binomial format P3's tagging Lambda
    # publishes (lowercase, underscores in place of any whitespace),
    # so "Bos taurus", "bos_taurus", and "  BOS\tTAURUS " all map to the
    # same canonical "bos_taurus".
    normalised_tags = [
        "_".join(str(t).lower().strip().split())
        for t in tags
        if str(t).strip()
    ]
    if not normalised_tags:
        return _response(400, {"error": "tags must contain at least one non-empty value"})

    filter_policy = {"tags": normalised_tags}

    endpoint_url = _build_endpoint_url(email)

    try:
        # Idempotency: remove any prior https subscription for this email
        # before creating a fresh one with the new tag list.
        removed = _unsubscribe_existing(email)

        result = sns.subscribe(
            TopicArn=TOPIC_ARN,
            Protocol="https",
            Endpoint=endpoint_url,
            Attributes={"FilterPolicy": json.dumps(filter_policy)},
            ReturnSubscriptionArn=True,
        )
    except ClientError as exc:
        return _response(500, {"error": str(exc)})

    # Fire-and-forget confirmation email so the user sees immediate proof
    # the subscription took effect, instead of waiting for the first
    # matching tag-event (which might never arrive for rarely-seen tags).
    _send_welcome_email(email, normalised_tags)

    return _response(
        200,
        {
            "subscription_arn": result["SubscriptionArn"],
            "subscribed_tags": tags,
            "email": email,
            "endpoint": endpoint_url,
            "removed_prior_subscriptions": removed,
            "note": (
                "Subscription created. A confirmation email has been sent. "
                "Future tag-event notifications will arrive when our "
                "tagging pipeline detects one of the species above in a "
                "newly uploaded image or video."
            ),
        },
    )
