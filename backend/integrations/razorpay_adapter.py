"""
DunnFlow - Razorpay Adapter

This module sits between the Razorpay API client and DunnFlow's
business logic.

Responsibilities:
    - Fetch payments/orders through razorpay_client
    - Normalize Razorpay responses
    - Convert Razorpay payment failures into DunnFlow's internal format
    - Keep Razorpay-specific field names out of the recovery engine

IMPORTANT:
    This module does NOT:
        - decide whether to retry
        - execute a payment
        - modify customer data
        - apply recovery policies

Those responsibilities remain inside DunnFlow's existing pipeline.
"""

from __future__ import annotations

from typing import Any

from backend.integrations.razorpay_client import RazorpayClient


# ---------------------------------------------------------------------------
# Razorpay -> DunnFlow error mapping
# ---------------------------------------------------------------------------

ERROR_CATEGORY_MAP = {
    # Authentication / authorization failures
    "authentication_error": "auth_failed",
    "authorization_failed": "auth_failed",
    "card_not_authorized": "auth_failed",
    "card_payment_not_allowed": "auth_failed",

    # Card expiry
    "card_expired": "card_expired",
    "expired_card": "card_expired",

    # Insufficient funds
    "insufficient_funds": "insufficient_funds",
    "balance_insufficient": "insufficient_funds",

    # Bank / gateway timeout
    "timeout": "bank_timeout",
    "bank_timeout": "bank_timeout",
    "gateway_timeout": "bank_timeout",
}


class RazorpayAdapter:
    """
    Converts Razorpay API responses into DunnFlow-compatible records.

    The adapter can be used with the existing RazorpayClient without
    changing the detection, diagnosis, decision, execution, or outcome
    modules.
    """

    def __init__(self, client: RazorpayClient | None = None):
        self.client = client or RazorpayClient()

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        """
        Convert a value to int safely.

        Razorpay amounts are represented in the smallest currency unit
        such as paise for INR.
        """
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_status(status: Any) -> str | None:
        """Normalize a Razorpay status value."""
        if status is None:
            return None

        return str(status).strip().lower()

    @staticmethod
    def _extract_error_code(payment: dict[str, Any]) -> str | None:
        """
        Extract the most useful error code from a Razorpay payment object.

        Razorpay responses can contain error information in different
        locations depending on the endpoint/test response.
        """

        direct_fields = (
            "error_code",
            "error_reason",
            "error_description",
        )

        for field in direct_fields:
            value = payment.get(field)

            if value:
                return str(value)

        error = payment.get("error")

        if isinstance(error, dict):
            for field in (
                "code",
                "reason",
                "description",
                "source",
            ):
                value = error.get(field)

                if value:
                    return str(value)

        return None

    @staticmethod
    def _extract_failure_reason(
        payment: dict[str, Any],
    ) -> str | None:
        """Extract a human-readable failure reason."""

        error = payment.get("error")

        if isinstance(error, dict):
            description = error.get("description")

            if description:
                return str(description)

            reason = error.get("reason")

            if reason:
                return str(reason)

        for field in (
            "error_description",
            "error_reason",
            "description",
        ):
            value = payment.get(field)

            if value:
                return str(value)

        return None

    @staticmethod
    def _classify_failure(
        error_code: str | None,
        failure_reason: str | None,
    ) -> str:
        """
        Convert Razorpay's error information into DunnFlow's
        internal failure categories.

        This classification is intentionally conservative.

        Unknown failures become 'unclassified' rather than being
        incorrectly assigned to a recovery strategy.
        """

        combined = " ".join(
            value.lower()
            for value in (
                error_code,
                failure_reason,
            )
            if value
        )

        # Exact / direct mapping first.
        if error_code:
            normalized_code = error_code.strip().lower()

            if normalized_code in ERROR_CATEGORY_MAP:
                return ERROR_CATEGORY_MAP[normalized_code]

        # Conservative keyword fallback.
        if any(
            keyword in combined
            for keyword in (
                "insufficient",
                "insufficient_funds",
                "balance",
            )
        ):
            return "insufficient_funds"

        if any(
            keyword in combined
            for keyword in (
                "expired",
                "card_expired",
            )
        ):
            return "card_expired"

        if any(
            keyword in combined
            for keyword in (
                "timeout",
                "timed out",
                "bank timeout",
            )
        ):
            return "bank_timeout"

        if any(
            keyword in combined
            for keyword in (
                "not authorized",
                "not_authorized",
                "authorization",
                "authentication",
                "declined",
            )
        ):
            return "auth_failed"

        return "unclassified"

    # ------------------------------------------------------------------
    # Payment normalization
    # ------------------------------------------------------------------

    def normalize_payment(
        self,
        payment: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Normalize a Razorpay payment into the DunnFlow payment format.

        Razorpay's raw payment ID is mapped to both:
            - payment_id
            - razorpay_payment_id

        This keeps the internal DunnFlow representation consistent
        while preserving the original Razorpay identifiers.
        """

        # Standard Razorpay API returns 'id'; fallback to 'payment_id'
        # if pre-processed.
        payment_id = payment.get("id") or payment.get("payment_id")
        order_id = payment.get("order_id")

        error_code = self._extract_error_code(payment)
        failure_reason = self._extract_failure_reason(payment)

        return {
    "payment_id": payment.get("payment_id"),

    "customer_id": (
        payment.get("contact")
        or payment.get("customer_id")
    ),

    "customer_name": payment.get("customer_name"),

    "customer_email": (
        payment.get("email")
        or payment.get("customer_email")
    ),

    "amount": payment.get("amount"),
    "currency": payment.get("currency"),

    "raw_error_code": (
        payment.get("error_code")
        or payment.get("raw_error_code")
    ),

    "failure_reason": (
        payment.get("error_description")
        or payment.get("failure_reason")
        or payment.get("error_reason")
    ),

    "failure_category": (
        payment.get("failure_category")
        or "unclassified"
    ),

    "status": payment.get("status"),

    "retry_count": payment.get(
        "retry_count",
        0,
    ),

    "last_attempt_at": payment.get(
        "last_attempt_at"
    ),

    "razorpay_payment_id": (
        payment.get("razorpay_payment_id")
        or payment.get("payment_id")
    ),

    "razorpay_order_id": (
        payment.get("razorpay_order_id")
        or payment.get("order_id")
    ),

    "method": payment.get("method"),

    "captured": payment.get("captured"),

    "amount_refunded": payment.get(
        "amount_refunded",
        0,
    ),

    "created": (
        payment.get("created")
        or payment.get("created_at")
    ),

    # IMPORTANT:
    # Preserve Razorpay notes so the ingestion
    # layer can resolve DunnFlow invoice mappings.
    "notes": payment.get("notes") or {},
}

    # ------------------------------------------------------------------
    # Fetch one payment
    # ------------------------------------------------------------------

    def get_payment(
        self,
        payment_id: str,
    ) -> dict[str, Any]:
        """
        Fetch one payment from Razorpay and normalize it.
        """

        raw_payment = self.client.fetch_payment(
            payment_id
        )

        return self.normalize_payment(
            raw_payment
        )

    # ------------------------------------------------------------------
    # Fetch payment collection
    # ------------------------------------------------------------------

    def get_payments(
        self,
        count: int = 100,
        skip: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Fetch a collection of Razorpay payments and normalize them.
        """

        raw_payments = self.client.fetch_payments(
            count=count,
            skip=skip,
        )

        # Razorpay collections normally look like:
        #
        # {
        #     "entity": "collection",
        #     "count": ...,
        #     "items": [...]
        # }

        if isinstance(raw_payments, dict):
            items = raw_payments.get(
                "items",
                [],
            )
        elif isinstance(raw_payments, list):
            items = raw_payments
        else:
            items = []

        return [
            self.normalize_payment(payment)
            for payment in items
            if isinstance(payment, dict)
        ]

    # ------------------------------------------------------------------
    # Failed payments only
    # ------------------------------------------------------------------

    def get_failed_payments(
        self,
        count: int = 100,
        skip: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Fetch Razorpay payments and return only failed payments.

        This is the main entry point that the DunnFlow detection
        layer can use when we connect real Razorpay Test Mode.
        """

        payments = self.get_payments(
            count=count,
            skip=skip,
        )

        return [
            payment
            for payment in payments
            if payment.get("status") == "failed"
        ]

    # ------------------------------------------------------------------
    # Payments belonging to an order
    # ------------------------------------------------------------------

    def get_order_payments(
        self,
        order_id: str,
    ) -> list[dict[str, Any]]:
        """
        Fetch payments belonging to a Razorpay order and normalize them.
        """

        raw_payments = (
            self.client.fetch_order_payments(
                order_id
            )
        )

        if isinstance(raw_payments, dict):
            items = raw_payments.get(
                "items",
                [],
            )
        elif isinstance(raw_payments, list):
            items = raw_payments
        else:
            items = []

        return [
            self.normalize_payment(payment)
            for payment in items
            if isinstance(payment, dict)
        ]

    # ------------------------------------------------------------------
    # Integration health
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """
        Return integration configuration information without
        making a payment or changing anything in Razorpay.
        """

        configured = bool(
            getattr(
                self.client,
                "configured",
                False,
            )
        )

        mode = getattr(
            self.client,
            "mode",
            "test",
        )

        return {
            "configured": configured,
            "mode": mode,
            "base_url": getattr(
                self.client,
                "base_url",
                None,
            ),
        }


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Safe command-line smoke test.

    It does NOT attempt to execute a payment.
    """

    adapter = RazorpayAdapter()

    health = adapter.health_check()

    print("=" * 68)
    print("DUNNFLOW RAZORPAY ADAPTER")
    print("=" * 68)

    print(
        f"Configured:       {health['configured']}"
    )

    print(
        f"Mode:              {health['mode']}"
    )

    print(
        f"Base URL:          {health['base_url']}"
    )

    print("=" * 68)

    if not health["configured"]:
        print(
            "Razorpay credentials are not configured."
        )
        print(
            "Adapter smoke test completed safely."
        )
        return

    print(
        "Razorpay adapter is configured."
    )
    print(
        "No payment operation was executed."
    )


if __name__ == "__main__":
    main()