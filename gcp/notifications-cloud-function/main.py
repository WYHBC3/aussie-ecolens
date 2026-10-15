"""
notifications-cloud-function
============================

Receives SNS HTTPS push notifications from AWS and forwards them to the
end user as a rich-HTML email via Resend.

This Cloud Function is the GCP half of the "Tag-based Notifications" feature
required by the assignment's multi-cloud rubric. The flow is:

    P3 Tagging Lambda ──publish──> SNS Topic (AWS)
                                     │
                                     │ HTTPS POST  (per subscription, filtered)
                                     ↓
                              this Cloud Function (GCP)
                                     │
                                     │ Resend API
                                     ↓
                               user's email inbox

How SNS knows WHO to email
--------------------------
Each user's subscription is created with the endpoint:

    https://<cloud-function-url>?email=<user_email>

The query string is preserved when SNS POSTs notifications, so this function
reads ``request.args["email"]`` to know who to send to. The per-user filter
policy on the subscription decides WHICH messages reach this function for
that subscription, so by the time we receive the request we already know
the recipient cares about these tags.

Message types handled
---------------------
* **SubscriptionConfirmation** — fired once when AWS first registers the
  subscription. The handler must GET the ``SubscribeURL`` for AWS to mark
  the subscription as confirmed.
* **Notification** — the normal tag-event push. We parse the inner SNS
  ``Message`` JSON (published by P3) and email the user.
* **UnsubscribeConfirmation** — log and acknowledge. AWS sends this when
  a subscription is removed.

Environment variables
---------------------
``RESEND_API_KEY``  Resend API key (re_...).
``SENDER_EMAIL``    Verified-sender ``From`` field. Defaults to Resend's
                    shared ``onboarding@resend.dev`` so the function works
                    out of the box without domain verification.

Security note
-------------
A production-grade deployment should verify the SNS message signature
(``Signature`` / ``SigningCertURL`` fields) against the AWS-provided cert
to prevent spoofed posts to the function URL. For this academic prototype
we instead rely on:
  * the function URL being unlisted,
  * the recipient email being scoped via the query string,
  * Resend's free-tier domain restricting outbound delivery to the
    account owner unless a verified custom domain is configured.

A TODO is left in ``_verify_sns_message`` for adding strict verification
later if marks for additional security are pursued.
"""

import json
import os
import urllib.request
from typing import Any

import functions_framework
import resend


RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
SENDER_EMAIL = os.environ.get(
    "SENDER_EMAIL",
    "Aussie EcoLens <onboarding@resend.dev>",
)

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY


def _verify_sns_message(body: dict) -> bool:
    """Lightweight SNS envelope sanity check.

    TODO (security hardening): replace with strict signature verification
    using ``Signature``, ``SigningCertURL``, and the message canonical
    string per AWS docs:
    https://docs.aws.amazon.com/sns/latest/dg/sns-verify-signature-of-message.html
    """
    return (
        isinstance(body, dict)
        and "TopicArn" in body
        and "Type" in body
    )


def _confirm_subscription(subscribe_url: str) -> int:
    """Confirm an SNS HTTPS subscription by GET'ing the URL AWS supplied."""
    with urllib.request.urlopen(subscribe_url, timeout=15) as resp:
        return resp.status


def _build_email_html(sns_message: dict) -> str:
    """Render the HTML body from P3's published payload.

    Expected P3 publish shape:
        {
          "file_id": "<sha256 hex>",
          "file_url": "<https url to media>",
          "tags": ["koala", "wombat"]
        }
    """
    file_id = sns_message.get("file_id", "(unknown)")
    file_url = sns_message.get("file_url", "")
    tags = sns_message.get("tags", []) or []
    tags_text = ", ".join(tags) if tags else "(no tags)"

    media_block = (
        f'<p><a href="{file_url}" '
        f'style="color:#0366d6;text-decoration:none;font-weight:600">'
        f'View the image &rarr;</a></p>'
        if file_url
        else ""
    )

    return f"""\
<!DOCTYPE html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1f2937;line-height:1.5;max-width:560px;margin:0 auto;padding:24px">
  <h2 style="color:#111;margin:0 0 16px">Aussie EcoLens — New observation</h2>
  <p>A new file was tagged with species you follow:</p>
  <p style="background:#f3f4f6;border-radius:6px;padding:8px 12px;display:inline-block;font-weight:600">
    {tags_text}
  </p>
  <p style="color:#4b5563;font-size:13px">File ID: <code>{file_id}</code></p>
  {media_block}
  <hr style="margin:24px 0;border:0;border-top:1px solid #e5e7eb">
  <p style="color:#9ca3af;font-size:11px">
    You received this email because you subscribed to one or more of these
    tags on Aussie EcoLens. To stop, sign in and update your notification
    preferences.
  </p>
</body></html>
"""


def _send_notification_email(to_email: str, sns_message: dict) -> Any:
    tags = sns_message.get("tags", []) or []
    tags_text = ", ".join(tags) if tags else "your subscribed tags"
    subject = f"Aussie EcoLens — new {tags_text} observation"
    html = _build_email_html(sns_message)

    return resend.Emails.send({
        "from": SENDER_EMAIL,
        "to": [to_email],
        "subject": subject,
        "html": html,
    })


def _send_welcome_email(to_email: str, tags: list) -> Any:
    """Send a subscription-confirmation email so users get immediate feedback
    that their preferences were saved. Without this, a user who subscribes
    but has no matching tag-event waiting could think the feature is broken.
    """
    tags_text = ", ".join(tags) if tags else "your selected species"
    subject = "Aussie EcoLens — subscription confirmed"

    html = f"""\
<!DOCTYPE html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1f2937;line-height:1.5;max-width:560px;margin:0 auto;padding:24px">
  <h2 style="color:#111;margin:0 0 16px">Aussie EcoLens — Subscription confirmed</h2>
  <p>You will now be notified by email whenever a new observation matches:</p>
  <p style="background:#dcfce7;border-left:4px solid #16a34a;border-radius:6px;padding:10px 14px;display:inline-block;font-weight:600;color:#14532d">
    {tags_text}
  </p>
  <p style="color:#4b5563;font-size:13px;margin-top:18px">
    No further action is required. Notifications will arrive automatically
    when our tagging pipeline detects one of the species above in a newly
    uploaded image or video.
  </p>
  <hr style="margin:24px 0;border:0;border-top:1px solid #e5e7eb">
  <p style="color:#9ca3af;font-size:11px">
    You can change or cancel your subscription at any time from the Aussie
    EcoLens dashboard.
  </p>
</body></html>
"""

    return resend.Emails.send({
        "from": SENDER_EMAIL,
        "to": [to_email],
        "subject": subject,
        "html": html,
    })


@functions_framework.http
def notifications(request):
    """Cloud Function HTTPS entrypoint.

    Returns a (body, status) tuple to be polite to AWS retry semantics:
    most error paths return 200 so SNS doesn't endlessly redeliver
    something that will never succeed (e.g. bad recipient). True
    routing/auth failures still return 4xx.
    """
    message_type = request.headers.get("x-amz-sns-message-type", "")
    aussie_message_type = request.headers.get("x-aussie-message-type", "")

    # Parse the JSON envelope. SNS uses Content-Type: text/plain even
    # though the body is JSON, so force=True is required.
    try:
        body = request.get_json(force=True, silent=False)
    except Exception as exc:
        print(f"Failed to parse request body as JSON: {exc}")
        return ("Bad JSON", 400)

    # Welcome path is invoked by the AWS notifications-subscribe Lambda
    # immediately after creating a new SNS subscription, so the end user
    # gets an instant subscription-confirmation email without having to
    # wait for the first matching tag event.
    if aussie_message_type == "welcome":
        to_email = (body or {}).get("email")
        tags = (body or {}).get("tags") or []
        if not to_email:
            return ("Missing recipient email", 400)
        try:
            result = _send_welcome_email(to_email, tags)
            print(f"Welcome email sent to {to_email}: {result}")
            return ("OK", 200)
        except Exception as exc:
            print(f"Resend welcome email failed for {to_email}: {exc}")
            # 200 so the subscribe Lambda doesn't fail the user-facing
            # request just because the welcome email had a hiccup.
            return ("Welcome send failed but acknowledged", 200)

    if not _verify_sns_message(body):
        print(f"Rejecting non-SNS request: {body!r}")
        return ("Not an SNS message", 400)

    if message_type == "SubscriptionConfirmation":
        subscribe_url = body.get("SubscribeURL")
        if not subscribe_url:
            return ("Missing SubscribeURL", 400)
        try:
            status = _confirm_subscription(subscribe_url)
            print(f"SNS subscription confirmed (status={status}): "
                  f"topic={body.get('TopicArn')}")
            return ("Subscription confirmed", 200)
        except Exception as exc:
            print(f"Failed to confirm SNS subscription: {exc}")
            return (f"Confirm failed: {exc}", 500)

    if message_type == "UnsubscribeConfirmation":
        print(f"Unsubscribe confirmation received for {body.get('TopicArn')}")
        return ("Acknowledged", 200)

    if message_type == "Notification":
        to_email = request.args.get("email")
        if not to_email:
            print("Notification dropped: no ?email= on request URL")
            # 200 to stop AWS retrying; the subscription is malformed.
            return ("Missing recipient email", 200)

        try:
            sns_message = json.loads(body.get("Message", "{}"))
        except json.JSONDecodeError as exc:
            print(f"Inner SNS Message JSON is malformed: {exc}")
            return ("Malformed inner Message", 200)

        try:
            result = _send_notification_email(to_email, sns_message)
            print(f"Email sent to {to_email}: {result}")
            return ("OK", 200)
        except Exception as exc:
            print(f"Resend email send failed: {exc}")
            # Acknowledge to AWS but log the failure — we don't want SNS
            # to keep retrying a failing Resend call.
            return ("Send failed but acknowledged", 200)

    print(f"Unknown SNS message type: {message_type!r}")
    return ("Unknown message type", 400)
