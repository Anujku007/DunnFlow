"""
DunnFlow - Razorpay Payment Ingestion

This module bridges the Razorpay integration layer and the DunnFlow
database.

Responsibilities:
    - Fetch payments from Razorpay through RazorpayAdapter
    - Import Razorpay payments into DunnFlow
    - Create payment-attempt records for failed payments
    - Preserve Razorpay payment/order identifiers
    - Record revenue-at-risk events for failed payments
    - Avoid duplicate ingestion of the same Razorpay payment
    - Safely skip Razorpay payments that cannot be mapped to a
      DunnFlow invoice
    - Keep Razorpay communication/business logic outside this module

Important:
    This module does NOT perform diagnosis or recovery decisions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.data.db import (
    create_payment_attempt,
    get_invoice,
    get_invoice_by_razorpay_id,
    get_payment_attempts,
    get_revenue_events,
    record_revenue_event,
)

from backend.integrations.razorpay_adapter import RazorpayAdapter


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BATCH_ID = "razorpay_test_ingestion"


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    """Return the current UTC timestamp."""

    return datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )


def _timestamp_from_epoch(value: Any) -> str:
    """
    Convert a Razorpay Unix timestamp into an ISO-8601 timestamp.

    If conversion fails, use the current UTC time.
    """

    if value is None:
        return _utc_now()

    try:
        timestamp = int(value)

        return datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc,
        ).isoformat(timespec="seconds")

    except (
        TypeError,
        ValueError,
        OSError,
        OverflowError,
    ):
        return _utc_now()


def _safe_int(
    value: Any,
    default: int = 0,
) -> int:
    """Safely convert a value to an integer."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Ingestion service
# ---------------------------------------------------------------------------

class RazorpayIngestion:
    """
    Import Razorpay payments into DunnFlow.

    This class does not perform diagnosis or recovery decisions.
    It translates external Razorpay payments into DunnFlow records.
    """

    def __init__(
        self,
        adapter: RazorpayAdapter | None = None,
    ) -> None:

        self.adapter = (
            adapter
            or RazorpayAdapter()
        )

    # -----------------------------------------------------------------------
    # Existing payment detection
    # -----------------------------------------------------------------------

    def _payment_already_ingested(
        self,
        razorpay_payment_id: str,
    ) -> bool:
        """
        Check whether a Razorpay payment has already been ingested.

        The Razorpay payment ID is used as the idempotency key.
        """

        if not razorpay_payment_id:
            return False

        attempts = get_payment_attempts()

        for attempt in attempts:

            if (
                attempt.get("razorpay_payment_id")
                == razorpay_payment_id
            ):
                return True

        return False

    # -----------------------------------------------------------------------
    # Existing revenue-event detection
    # -----------------------------------------------------------------------

    def _revenue_event_already_recorded(
        self,
        razorpay_payment_id: str,
    ) -> bool:
        """
        Check whether a revenue event has already been recorded.
        """

        if not razorpay_payment_id:
            return False

        events = get_revenue_events()

        marker = (
            f"Razorpay payment "
            f"{razorpay_payment_id}"
        )

        for event in events:

            detail = event.get("detail") or ""

            if marker in detail:
                return True

        return False

    # -----------------------------------------------------------------------
    # Payment attempt creation
    # -----------------------------------------------------------------------

    def _build_payment_attempt(
        self,
        payment: dict[str, Any],
        *,
        batch_id: str,
    ) -> dict[str, Any]:
        """
        Convert a normalized Razorpay payment into a DunnFlow
        payment-attempt record.

        This method is only called after a valid DunnFlow invoice
        mapping has been confirmed.
        """

        payment_id = (
            payment.get("razorpay_payment_id")
            or payment.get("payment_id")
        )

        status = (
            payment.get("status")
            or "unknown"
        )

        if status == "failed":

            result = "failed"

        elif status in {
            "captured",
            "authorized",
        }:

            result = "succeeded"

        else:

            result = status

        created_at = _timestamp_from_epoch(
            payment.get("created")
            or payment.get("created_at")
        )

        failure_reason = (
            payment.get("failure_reason")
            or payment.get("error_description")
            or payment.get("error_reason")
        )

        raw_error_code = (
            payment.get("raw_error_code")
            or payment.get("error_code")
        )

        return {
            "batch_id": batch_id,

            "invoice_id": payment.get(
                "invoice_id"
            ),

            "subscription_id": payment.get(
                "subscription_id"
            ),

            "razorpay_payment_id": payment_id,

            "attempt_number": 1,

            "attempt_type": "external_razorpay",

            "action_type": "razorpay_payment_ingestion",

            "scheduled_for": created_at,

            "executed_at": created_at,

            "result": result,

            "raw_error_code": raw_error_code,

            "failure_reason": failure_reason,

            "gateway_status": status,

            "result_detail": (
                "Imported from Razorpay Test Mode. "
                f"Razorpay payment={payment_id}."
            ),

            "created_at": created_at,
        }

    # -----------------------------------------------------------------------
    # Revenue-at-risk event
    # -----------------------------------------------------------------------

    def _build_revenue_event(
        self,
        payment: dict[str, Any],
        *,
        batch_id: str,
        payment_attempt_id: int,
    ) -> dict[str, Any]:
        """
        Build a revenue-at-risk event for a failed payment.
        """

        payment_id = (
            payment.get("razorpay_payment_id")
            or payment.get("payment_id")
        )

        amount = _safe_int(
            payment.get("amount")
        )

        created_at = _timestamp_from_epoch(
            payment.get("created")
            or payment.get("created_at")
        )

        return {
            "batch_id": batch_id,

            "subscription_id": payment.get(
                "subscription_id"
            ),

            "invoice_id": payment.get(
                "invoice_id"
            ),

            "payment_attempt_id": payment_attempt_id,

            "event_type": "revenue_at_risk",

            "amount": amount,

            "razorpay_event_id": payment_id,

            "event_timestamp": created_at,

            "detail": (
                "Razorpay Test Mode payment "
                f"{payment_id} was imported into DunnFlow."
            ),
        }

    # -----------------------------------------------------------------------
    # Invoice mapping resolution
    # -----------------------------------------------------------------------

    def _resolve_invoice_mapping(
        self,
        payment: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        """
        Resolve a Razorpay payment to a DunnFlow invoice.

        Resolution order:
            1. Explicit normalized invoice_id
            2. Razorpay invoice ID
            3. DunnFlow invoice marker in Razorpay notes

        Returns:
            (invoice_id, subscription_id)
        """

        # ---------------------------------------------------------------
        # 1. Explicit local invoice mapping
        # ---------------------------------------------------------------

        invoice_id = payment.get("invoice_id")

        if invoice_id:
            invoice = get_invoice(invoice_id)

            if invoice:
                return (
                    invoice["invoice_id"],
                    invoice.get("subscription_id"),
                )

        # ---------------------------------------------------------------
        # 2. Razorpay invoice ID
        # ---------------------------------------------------------------

        razorpay_invoice_id = (
            payment.get("razorpay_invoice_id")
            or payment.get("invoice_id_external")
        )

        if razorpay_invoice_id:
            invoice = get_invoice_by_razorpay_id(
                razorpay_invoice_id
            )

            if invoice:
                return (
                    invoice["invoice_id"],
                    invoice.get("subscription_id"),
                )

        # ---------------------------------------------------------------
        # 3. DunnFlow mapping marker in Razorpay notes
        #
        # Example:
        # {
        #     "dunnflow_invoice_id": "inv_dunnflow_001"
        # }
        # ---------------------------------------------------------------

        notes = payment.get("notes") or {}

        marker_invoice_id = notes.get(
            "dunnflow_invoice_id"
        )

        if marker_invoice_id:
            invoice = get_invoice(
                marker_invoice_id
            )

            if invoice:
                return (
                    invoice["invoice_id"],
                    invoice.get("subscription_id"),
                )

        return None, None

    # -----------------------------------------------------------------------
    # Single payment ingestion
    # -----------------------------------------------------------------------

    def ingest_payment(
        self,
        payment: dict[str, Any],
        *,
        batch_id: str = DEFAULT_BATCH_ID,
    ) -> dict[str, Any]:
        """
        Ingest one normalized Razorpay payment.

        Payments without a DunnFlow invoice mapping are skipped safely.
        """

        payment_id = (
            payment.get("razorpay_payment_id")
            or payment.get("payment_id")
        )

        # ---------------------------------------------------------------
        # Payment ID is mandatory
        # ---------------------------------------------------------------

        if not payment_id:

            return {
                "status": "skipped",
                "reason": (
                    "missing_razorpay_payment_id"
                ),
            }

        # ---------------------------------------------------------------
        # Idempotency
        # ---------------------------------------------------------------

        if self._payment_already_ingested(
            payment_id
        ):

            return {
                "status": "skipped",
                "reason": "already_ingested",
                "razorpay_payment_id": payment_id,
            }

        # ---------------------------------------------------------------
        # DunnFlow invoice mapping
        #
        # payment_attempts.invoice_id is NOT NULL.
        #
        # Therefore we MUST NOT create a payment attempt unless
        # a local DunnFlow invoice exists.
        # ---------------------------------------------------------------

        invoice_id, subscription_id = (
            self._resolve_invoice_mapping(payment)
        )

        if not invoice_id:

            order_id = (
                payment.get("razorpay_order_id")
                or payment.get("order_id")
            )

            return {
                "status": "skipped",
                "reason": "no_dunnflow_invoice_mapping",
                "razorpay_payment_id": payment_id,
                "razorpay_order_id": order_id,
            }
# ---------------------------------------------------------------
# Resolve the authoritative DunnFlow batch from the invoice.
#
# The local invoice is the source of truth for batch ownership.
# This prevents a foreign-key violation when ingestion is invoked
# with its default external/test batch ID.
# ---------------------------------------------------------------    
        invoice = get_invoice(invoice_id)
        if not invoice:
            return{
                "status": "skipped",
                "reason": "dunnflow_invoice_not_found",
                "razorpay_payment_id": payment_id,
                "invoice_id": invoice_id,
            }
        resolved_batch_id = invoice["batch_id"]

        payment["invoice_id"] = invoice_id

        if subscription_id:
            payment["subscription_id"] = subscription_id

        # ---------------------------------------------------------------
        # Create payment attempt
        # ---------------------------------------------------------------

        attempt = self._build_payment_attempt(
            payment,
            batch_id=resolved_batch_id,
        )

        attempt_id = create_payment_attempt(
            attempt
        )

        result = {
            "status": "ingested",

            "razorpay_payment_id": payment_id,

            "payment_attempt_id": attempt_id,

            "payment_status": payment.get(
                "status"
            ),

            "amount": _safe_int(
                payment.get("amount")
            ),
        }

        # ---------------------------------------------------------------
        # Failed payments become revenue-at-risk events.
        # ---------------------------------------------------------------

        if payment.get("status") == "failed":

            if not self._revenue_event_already_recorded(
                payment_id
            ):

                event = self._build_revenue_event(
                    payment,
                    batch_id=resolved_batch_id,
                    payment_attempt_id=attempt_id,
                )

                event_id = record_revenue_event(
                    event
                )

                result[
                    "revenue_event_id"
                ] = event_id

        return result

    # -----------------------------------------------------------------------
    # Multiple payment ingestion
    # -----------------------------------------------------------------------

    def ingest_payments(
        self,
        *,
        count: int = 10,
        skip: int = 0,
        batch_id: str = DEFAULT_BATCH_ID,
        failed_only: bool = False,
    ) -> dict[str, Any]:
        """
        Fetch payments from Razorpay and ingest them.

        Payments that cannot be mapped to a DunnFlow invoice are
        skipped safely.
        """

        payments = self.adapter.get_payments(
            count=count,
            skip=skip,
        )

        processed = 0
        ingested = 0
        skipped = 0
        failed_ingested = 0
        successful_ingested = 0

        results: list[dict[str, Any]] = []

        for payment in payments:

            # -----------------------------------------------------------
            # Failed-only filter
            # -----------------------------------------------------------

            if (
                failed_only
                and payment.get("status")
                != "failed"
            ):
                continue

            processed += 1

            result = self.ingest_payment(
                payment,
                batch_id=batch_id,
            )

            results.append(result)

            # -----------------------------------------------------------
            # Result counters
            # -----------------------------------------------------------

            if result.get("status") == "ingested":

                ingested += 1

                if payment.get("status") == "failed":

                    failed_ingested += 1

                else:

                    successful_ingested += 1

            elif result.get("status") == "skipped":

                skipped += 1

        return {
            "batch_id": batch_id,

            "requested_count": count,

            "skip": skip,

            "processed": processed,

            "ingested": ingested,

            "skipped": skipped,

            "failed_ingested": failed_ingested,

            "successful_ingested": successful_ingested,

            "results": results,
        }


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def ingest_razorpay_payments(
    *,
    count: int = 10,
    skip: int = 0,
    batch_id: str = DEFAULT_BATCH_ID,
    failed_only: bool = False,
) -> dict[str, Any]:
    """
    Convenience wrapper for Razorpay payment ingestion.
    """

    ingestion = RazorpayIngestion()

    return ingestion.ingest_payments(
        count=count,
        skip=skip,
        batch_id=batch_id,
        failed_only=failed_only,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Run a Razorpay Test Mode ingestion demonstration.
    """

    print("=" * 68)
    print("DUNNFLOW RAZORPAY INGESTION")
    print("=" * 68)

    try:

        ingestion = RazorpayIngestion()

        health = ingestion.adapter.health_check()

        print(
            f"Configured:       "
            f"{health.get('configured')}"
        )

        print(
            f"Mode:             "
            f"{health.get('mode')}"
        )

        print(
            f"Base URL:         "
            f"{health.get('base_url')}"
        )

        print("=" * 68)

        if not health.get("configured"):

            print(
                "Razorpay credentials are not configured."
            )

            return

        report = ingestion.ingest_payments(
            count=10,
            batch_id=DEFAULT_BATCH_ID,
            failed_only=True,
        )

        print(
            f"Payments processed: "
            f"{report['processed']}"
        )

        print(
            f"Payments ingested:   "
            f"{report['ingested']}"
        )

        print(
            f"Payments skipped:    "
            f"{report['skipped']}"
        )

        print(
            f"Failed ingested:     "
            f"{report['failed_ingested']}"
        )

        print("=" * 68)

        for result in report["results"]:

            print(
                result.get(
                    "razorpay_payment_id",
                    "-"
                ),
                "|",
                result.get("status"),
                "|",
                result.get("reason", ""),
            )

    except Exception as exc:

        print(
            "Razorpay ingestion failed:"
        )

        print(
            f"{type(exc).__name__}: {exc}"
        )


if __name__ == "__main__":
    main()
