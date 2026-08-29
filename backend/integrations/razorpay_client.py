"""
DunnFlow - Razorpay API Client

This module is the ONLY layer responsible for communicating
with Razorpay.

Responsibilities:
    - Load Razorpay credentials from environment variables / .env
    - Detect Test vs Live mode
    - Fetch individual payments
    - Fetch payment collections
    - Fetch payments belonging to an order
    - Normalize Razorpay responses for DunnFlow
    - Keep Razorpay-specific logic isolated from the pipeline

IMPORTANT:
    DunnFlow should never call the Razorpay API directly from
    detection, diagnosis, decision, execution, or outcome modules.

    Those modules should communicate through this client.
"""

from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

load_dotenv()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")

RAZORPAY_MODE = os.getenv("RAZORPAY_MODE", "test").strip().lower()

RAZORPAY_BASE_URL = "https://api.razorpay.com/v1"

DEFAULT_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RazorpayClientError(Exception):
    """Base exception for DunnFlow Razorpay client errors."""


class RazorpayConfigurationError(RazorpayClientError):
    """Raised when Razorpay credentials/configuration are missing."""


class RazorpayAPIError(RazorpayClientError):
    """Raised when Razorpay returns an API error."""


# ---------------------------------------------------------------------------
# Razorpay Client
# ---------------------------------------------------------------------------


class RazorpayClient:
    """
    Thin wrapper around the Razorpay REST API.

    This class intentionally contains no DunnFlow business logic.
    It only handles communication with Razorpay and normalization
    of API responses.
    """

    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
        mode: str | None = None,
    ) -> None:

        self.key_id = key_id or RAZORPAY_KEY_ID
        self.key_secret = key_secret or RAZORPAY_KEY_SECRET

        self.mode = (
            mode or RAZORPAY_MODE
        ).strip().lower()

        if self.mode not in {"test", "live"}:
            raise RazorpayConfigurationError(
                "RAZORPAY_MODE must be either 'test' or 'live'."
            )

        self.base_url = RAZORPAY_BASE_URL

        self.configured = bool(
            self.key_id and self.key_secret
        )

        self.session = requests.Session()

        if self.configured:
            self.session.auth = (
                self.key_id,
                self.key_secret,
            )

        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "DunnFlow/1.0",
            }
        )

    def _require_credentials(self) -> None:
        if not self.configured:
            raise RazorpayConfigurationError(
                "Razorpay credentials are not configured."
            )

    # -----------------------------------------------------------------------
    # Configuration helpers
    # -----------------------------------------------------------------------

    def is_test_mode(self) -> bool:
        """Return True when DunnFlow is operating in Razorpay Test Mode."""

        return self.mode == "test"

    def is_live_mode(self) -> bool:
        """Return True when DunnFlow is operating in Razorpay Live Mode."""

        return self.mode == "live"

    def get_mode(self) -> str:
        """Return current Razorpay mode."""

        return self.mode

    # -----------------------------------------------------------------------
    # Internal HTTP request
    # -----------------------------------------------------------------------

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        self._require_credentials()

        url = f"{self.base_url}{endpoint}"

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json,
                timeout=DEFAULT_TIMEOUT,
            )

        except requests.RequestException as exc:
            raise RazorpayAPIError(
                f"Unable to communicate with Razorpay: {exc}"
            ) from exc

        if not response.ok:

            try:
                error_body = response.json()
            except ValueError:
                error_body = response.text

            raise RazorpayAPIError(
                f"Razorpay API request failed "
                f"(HTTP {response.status_code}): "
                f"{error_body}"
            )

        try:
            return response.json()

        except ValueError as exc:
            raise RazorpayAPIError(
                "Razorpay returned an invalid JSON response."
            ) from exc

    # -----------------------------------------------------------------------
    # Payments
    # -----------------------------------------------------------------------

    def fetch_payment(
        self,
        payment_id: str,
    ) -> dict[str, Any]:

        """
        Fetch one Razorpay payment.

        Example:
            pay_xxxxxxxxxxxxxx
        """

        if not payment_id:
            raise ValueError(
                "payment_id cannot be empty."
            )

        data = self._request(
            "GET",
            f"/payments/{payment_id}",
        )

        return self.normalize_payment(data)

    # -----------------------------------------------------------------------

    def fetch_payments(
        self,
        *,
        count: int = 10,
        skip: int = 0,
    ) -> list[dict[str, Any]]:

        """
        Fetch a collection of Razorpay payments.

        count:
            Number of payments to request.

        skip:
            Number of payments to skip.
        """

        if count < 1:
            raise ValueError(
                "count must be greater than zero."
            )

        if skip < 0:
            raise ValueError(
                "skip cannot be negative."
            )

        data = self._request(
            "GET",
            "/payments",
            params={
                "count": count,
                "skip": skip,
            },
        )

        items = data.get("items", [])

        return [
            self.normalize_payment(payment)
            for payment in items
        ]

    # -----------------------------------------------------------------------
    # Order payments
    # -----------------------------------------------------------------------

    def fetch_order_payments(
        self,
        order_id: str,
    ) -> list[dict[str, Any]]:

        """
        Fetch all payments belonging to a Razorpay order.
        """

        if not order_id:
            raise ValueError(
                "order_id cannot be empty."
            )

        data = self._request(
            "GET",
            f"/orders/{order_id}/payments",
        )

        items = data.get("items", [])

        return [
            self.normalize_payment(payment)
            for payment in items
        ]

    # -----------------------------------------------------------------------
    # Payment collection with pagination
    # -----------------------------------------------------------------------

    def fetch_all_payments(
        self,
        *,
        page_size: int = 100,
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:

        """
        Fetch multiple pages of Razorpay payments.

        This is intentionally bounded so DunnFlow cannot accidentally
        request an unlimited number of payments.
        """

        if page_size < 1:
            raise ValueError(
                "page_size must be greater than zero."
            )

        if max_pages < 1:
            raise ValueError(
                "max_pages must be greater than zero."
            )

        all_payments: list[dict[str, Any]] = []

        for page in range(max_pages):

            payments = self.fetch_payments(
                count=page_size,
                skip=page * page_size,
            )

            if not payments:
                break

            all_payments.extend(payments)

            if len(payments) < page_size:
                break

        return all_payments

    # -----------------------------------------------------------------------
    # Payment normalization
    # -----------------------------------------------------------------------

    @staticmethod
    def normalize_payment(
        payment: dict[str, Any],
    ) -> dict[str, Any]:

        """
        Convert a Razorpay payment response into the normalized
        structure expected by DunnFlow.

        Razorpay-specific fields remain available under `raw`.
        """

        return {
            "payment_id": payment.get("id"),
            "order_id": payment.get("order_id"),
            "amount": payment.get("amount"),
            "currency": payment.get("currency"),
            "status": payment.get("status"),
            "method": payment.get("method"),
            "captured": payment.get("captured"),
            "description": payment.get("description"),
            "email": payment.get("email"),
            "contact": payment.get("contact"),

            "error_code": payment.get("error_code"),
            "error_description": payment.get("error_description"),
            "error_reason": payment.get("error_reason"),
            "error_source": payment.get("error_source"),
            "error_step": payment.get("error_step"),

            "created_at": payment.get("created_at"),

            # IMPORTANT
            "notes": payment.get("notes") or {},

            "raw": payment,
        }

    # -----------------------------------------------------------------------
    # DunnFlow failure normalization
    # -----------------------------------------------------------------------

    @staticmethod
    def normalize_failure(
        payment: dict[str, Any],
    ) -> dict[str, Any]:

        """
        Convert a normalized Razorpay payment into a DunnFlow
        failure event.

        This does NOT decide the failure category.

        Diagnosis remains responsible for determining whether
        the failure is:

            insufficient_funds
            card_expired
            bank_timeout
            auth_failed
            unclassified
        """

        return {
            "payment_id": payment.get("payment_id"),
            "order_id": payment.get("order_id"),
            "amount": payment.get("amount", 0),
            "currency": payment.get(
                "currency",
                "INR",
            ),
            "raw_error_code": payment.get(
                "error_code"
            ),
            "failure_reason": payment.get(
                "error_description"
            ),
            "status": "failed",
            "source": "razorpay",
            "mode": RAZORPAY_MODE,
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_razorpay_client() -> RazorpayClient:
    """
    Create a configured Razorpay client.

    Keeping construction behind this function makes it easier to
    replace the real client with a synthetic test client later.
    """

    return RazorpayClient()


# ---------------------------------------------------------------------------
# Safe configuration check
# ---------------------------------------------------------------------------


def check_configuration() -> dict[str, Any]:
    """
    Check Razorpay configuration without making an API request.

    Secrets are NEVER returned.
    """

    return {
        "configured": bool(
            RAZORPAY_KEY_ID
            and RAZORPAY_KEY_SECRET
        ),
        "mode": RAZORPAY_MODE,
        "base_url": RAZORPAY_BASE_URL,
        "key_id_present": bool(
            RAZORPAY_KEY_ID
        ),
        "key_secret_present": bool(
            RAZORPAY_KEY_SECRET
        ),
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------


def main() -> None:
    """
    Basic configuration test.

    This does not make a payment and does not modify Razorpay data.
    """

    print("=" * 68)
    print("DUNNFLOW RAZORPAY CLIENT")
    print("=" * 68)

    config = check_configuration()

    print(
        f"Configured:       {config['configured']}"
    )

    print(
        f"Mode:              {config['mode']}"
    )

    print(
        f"Base URL:          {config['base_url']}"
    )

    print(
        f"Key ID present:    {config['key_id_present']}"
    )

    print(
        f"Key secret present:{config['key_secret_present']}"
    )

    print("=" * 68)

    if config["configured"]:
        print(
            "Razorpay client configuration looks valid."
        )
    else:
        print(
            "Razorpay credentials are not configured."
        )

    print("=" * 68)


if __name__ == "__main__":
    main()