"""DunnFlow Razorpay webhook handler."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.integrations.razorpay_adapter import RazorpayAdapter
from backend.integrations.razorpay_ingestion import RazorpayIngestion
from backend.data.db import record_webhook_event, webhook_event_exists


class WebhookHandlerError(Exception):
    """Raised when a Razorpay webhook cannot be processed."""


def handle_razorpay_webhook(
    payload: dict[str, Any],
    *,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Handle one verified Razorpay webhook payload."""

    if not isinstance(payload, dict):
        raise WebhookHandlerError(
            "Webhook payload must be a JSON object."
        )

    event_type = payload.get("event")

    if not event_type:
        raise WebhookHandlerError(
            "Webhook event type is missing."
        )

    if event_id and webhook_event_exists(event_id):
        return {
            "status": "duplicate",
            "event": event_type,
            "event_id": event_id,
        }

    payload_data = payload.get("payload") or {}
    payment_data = payload_data.get("payment") or {}
    payment_entity = payment_data.get("entity")

    supported_payment_events = {
        "payment.captured",
        "payment.authorized",
        "payment.failed",
        "order.paid",
    }

    if event_type in supported_payment_events:

        if not isinstance(payment_entity, dict):
            raise WebhookHandlerError(
                "Razorpay payment entity is missing from webhook payload."
            )

        adapter = RazorpayAdapter.__new__(RazorpayAdapter)

        normalized_payment = adapter.normalize_payment(
            payment_entity
        )

        if event_type == "order.paid":
            normalized_payment["status"] = "captured"

        ingestion = RazorpayIngestion.__new__(
            RazorpayIngestion
        )

        result = ingestion.ingest_payment(
            normalized_payment
        )

        if event_id:
            record_webhook_event(
                event_id,
                event_type,
                datetime.now(timezone.utc).isoformat(),
            )

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