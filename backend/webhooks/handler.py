"""DunnFlow Razorpay webhook handler."""

from __future__ import annotations

from typing import Any

from backend.integrations.razorpay_adapter import RazorpayAdapter
from backend.integrations.razorpay_ingestion import RazorpayIngestion


class WebhookHandlerError(Exception):
    """Raised when a Razorpay webhook cannot be processed."""


def handle_razorpay_webhook(
    payload: dict[str, Any],
    *,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Handle one verified Razorpay webhook payload.

    Signature verification is intentionally performed by the API boundary
    before this function is called.
    """
    if not isinstance(payload, dict):
        raise WebhookHandlerError("Webhook payload must be a JSON object.")

    event_type = payload.get("event")

    if not event_type:
        raise WebhookHandlerError("Webhook event type is missing.")

    payload_data = payload.get("payload") or {}
    payment_data = payload_data.get("payment") or {}
    payment_entity = payment_data.get("entity")

    if not isinstance(payment_entity, dict):
        raise WebhookHandlerError(
            "Razorpay payment entity is missing from webhook payload."
        )

    if event_type.startswith("payment."):
        adapter = RazorpayAdapter.__new__(RazorpayAdapter)
        normalized_payment = adapter.normalize_payment(payment_entity)

        ingestion = RazorpayIngestion.__new__(RazorpayIngestion)
        result = ingestion.ingest_payment(normalized_payment)

        return {
            "status": "processed",
            "event": event_type,
            "event_id": event_id,
            "result": result,
        }

    return {
        "status": "ignored",
        "event": event_type,
        "event_id": event_id,
        "reason": "unsupported_event_type",
    }
