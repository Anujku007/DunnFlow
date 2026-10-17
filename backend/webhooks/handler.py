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

        # Do not infer capture solely from the event name.
        if event_type in {"payment.captured", "order.paid"}:
            if normalized_payment.get("status") != "captured":
                return {
                    "status": "rejected",
                    "event": event_type,
                    "event_id": event_id,
                    "reason": "payment_entity_not_captured",
                }

        # Validate an isolated demo payment before financial ingestion.
        order_id = normalized_payment.get("razorpay_order_id")
        if order_id:
            from backend.data.db import get_invoice
            from backend.data.razorpay_demo import (
                get_razorpay_demo_session_by_order_id,
            )

            demo_session = get_razorpay_demo_session_by_order_id(order_id)
            if demo_session:
                invoice = get_invoice(demo_session["invoice_id"])

                try:
                    payment_amount = int(payment_entity.get("amount"))
                    expected_amount = int(demo_session.get("amount_paise"))
                except (TypeError, ValueError):
                    payment_amount = -1
                    expected_amount = -2

                payment_currency = str(
                    payment_entity.get("currency") or ""
                ).upper()
                expected_currency = str(
                    demo_session.get("currency") or ""
                ).upper()

                if (
                    demo_session.get("razorpay_order_id") != order_id
                    or not invoice
                    or invoice.get("invoice_id") != demo_session.get("invoice_id")
                    or invoice.get("razorpay_order_id") != order_id
                    or payment_amount != expected_amount
                    or not payment_currency
                    or payment_currency != expected_currency
                ):
                    return {
                        "status": "rejected",
                        "event": event_type,
                        "event_id": event_id,
                        "reason": "demo_payment_mapping_amount_or_currency_mismatch",
                    }
        ingestion = RazorpayIngestion.__new__(
            RazorpayIngestion
        )

        result = ingestion.ingest_payment(
            normalized_payment
        )

        # Update only the session belonging to this exact Razorpay order.
        # The stored invoice status is authoritative.
        if normalized_payment.get("status") == "captured":
            from backend.data.db import get_invoice
            from backend.data.razorpay_demo import (
                get_razorpay_demo_session_by_order_id,
                update_razorpay_demo_session_status,
            )

            order_id = normalized_payment.get("razorpay_order_id")
            session = (
                get_razorpay_demo_session_by_order_id(order_id)
                if order_id
                else None
            )

            if session:
                invoice = get_invoice(session["invoice_id"])
                if (
                    invoice
                    and invoice.get("invoice_id") == session["invoice_id"]
                    and invoice.get("razorpay_order_id") == order_id
                    and invoice.get("status") == "paid"
                ):
                    update_razorpay_demo_session_status(
                        session["session_id"],
                        "paid",
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