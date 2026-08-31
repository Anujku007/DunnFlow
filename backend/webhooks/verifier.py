"""DunnFlow - Razorpay webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac

from backend.integrations.razorpay_client import RAZORPAY_WEBHOOK_SECRET


class WebhookVerificationError(ValueError):
    """Raised when a Razorpay webhook cannot be authenticated."""


def verify_razorpay_signature(raw_body: bytes, signature: str) -> bool:
    """Verify a Razorpay webhook signature against the raw request body.

    Razorpay signs the exact raw webhook payload using HMAC-SHA256 and the
    webhook secret. The caller must provide the request body before JSON
    parsing or re-serialization.
    """
    if not RAZORPAY_WEBHOOK_SECRET:
        raise WebhookVerificationError(
            "RAZORPAY_WEBHOOK_SECRET is not configured."
        )

    if not raw_body:
        raise WebhookVerificationError("Webhook body is empty.")

    if not signature:
        raise WebhookVerificationError(
            "X-Razorpay-Signature header is missing."
        )

    expected_signature = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)
