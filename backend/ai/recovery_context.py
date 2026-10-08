"""DunnFlow deterministic recovery context builder.

Builds a complete database-backed recovery context for the AI advisor.
This module is read-only and never authorizes or executes payments.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.data.db import (
    get_audit_log,
    get_invoice,
    get_payment_attempts,
    get_recovery_actions,
    get_revenue_events,
    get_subscription,
)


@dataclass(frozen=True)
class RecoveryContext:
    """Deterministic snapshot of one revenue recovery case."""

    invoice: dict[str, Any]
    subscription: dict[str, Any]
    customer: dict[str, Any]
    failure_category: str | None
    raw_gateway_error: str | None
    failure_reason: str | None
    invoice_amount: int
    payment_attempts: list[dict[str, Any]]
    recovery_actions: list[dict[str, Any]]
    retry_count: int
    time_since_previous_retry_seconds: float | None
    previous_recovery_actions: list[dict[str, Any]]
    invoice_status: str | None
    customer_action_history: list[dict[str, Any]]
    revenue_events: list[dict[str, Any]]
    audit_history: list[dict[str, Any]]

    # ------------------------------------------------------------------
    # AI DECISION HISTORY
    #
    # Historical context used by the AI advisor to improve its current
    # recommendation. This is advisory intelligence only.
    #
    # Deterministic policy remains the final authority for financial
    # actions.
    # ------------------------------------------------------------------

    historical_decisions: list[dict[str, Any]] = field(default_factory=list)
    historical_ai_recommendations: list[dict[str, Any]] = field(default_factory=list)
    historical_outcomes: list[dict[str, Any]] = field(default_factory=list)


    def to_dict(self) -> dict[str, Any]:
        """Return the context as a plain dictionary."""
        return asdict(self)


class RecoveryContextError(Exception):
    """Raised when required recovery context is unavailable."""


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse a stored ISO timestamp into an aware UTC datetime."""
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _latest_failed_attempt(
    attempts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the latest failed payment attempt."""
    failed = [
        attempt
        for attempt in attempts
        if str(attempt.get("result", "")).lower()
        in {"failed", "failure"}
    ]

    if not failed:
        return None

    return max(
        failed,
        key=lambda attempt: (
            int(attempt.get("attempt_number") or 0),
            _parse_timestamp(attempt.get("created_at"))
            or datetime.min.replace(tzinfo=timezone.utc),
        ),
    )


def _previous_retry_timestamp(
    attempts: list[dict[str, Any]],
) -> datetime | None:
    """Return the timestamp of the latest recovery attempt."""
    recovery_attempts = [
        attempt
        for attempt in attempts
        if str(attempt.get("attempt_type", "")).lower()
        in {"recovery", "recovery_payment", "customer_payment"}
    ]

    timestamps = [
        _parse_timestamp(
            attempt.get("executed_at")
            or attempt.get("created_at")
        )
        for attempt in recovery_attempts
    ]

    timestamps = [
        timestamp
        for timestamp in timestamps
        if timestamp is not None
    ]

    return max(timestamps) if timestamps else None


def _customer_context(
    subscription: dict[str, Any],
) -> dict[str, Any]:
    """Extract customer information from subscription state."""
    return {
        "customer_id": subscription.get("customer_id"),
        "customer_name": subscription.get("customer_name"),
        "customer_email": subscription.get("customer_email"),
    }


def build_recovery_context(
    invoice_id: str,
    *,
    as_of: str | datetime | None = None,
) -> RecoveryContext:
    """Build a deterministic, read-only recovery context."""

    invoice = get_invoice(invoice_id)

    if not invoice:
        raise RecoveryContextError(
            f"Invoice '{invoice_id}' does not exist."
        )

    subscription_id = invoice.get("subscription_id")

    subscription = (
        get_subscription(subscription_id)
        if subscription_id
        else None
    )

    if not subscription:
        raise RecoveryContextError(
            f"Subscription context is missing for "
            f"invoice '{invoice_id}'."
        )

    payment_attempts = get_payment_attempts(
        invoice_id=invoice_id
    )

    recovery_actions = get_recovery_actions(
        invoice_id=invoice_id
    )

    revenue_events = get_revenue_events(
        invoice_id=invoice_id
    )

    audit_history = get_audit_log(
        invoice_id=invoice_id
    )

    latest_failed = _latest_failed_attempt(
        payment_attempts
    )

    retry_count = sum(
        1
        for attempt in payment_attempts
        if str(attempt.get("attempt_type", "")).lower()
        in {"recovery", "recovery_payment", "customer_payment"}
    )

    previous_retry = _previous_retry_timestamp(
        payment_attempts
    )

    reference_time = (
        _parse_timestamp(as_of)
        if as_of
        else datetime.now(timezone.utc)
    )

    time_since_previous_retry_seconds = None

    if previous_retry:
        time_since_previous_retry_seconds = max(
            0.0,
            (
                reference_time - previous_retry
            ).total_seconds(),
        )

    previous_recovery_actions = [
        action
        for action in recovery_actions
        if action.get("status") not in {
            "planned",
            "awaiting_customer",
        }
        or action.get("executed_at")
    ]

    customer_action_history = [
        action
        for action in recovery_actions
        if action.get("action_type") in {
            "customer_action",
            "payment_method_update",
        }
        or action.get("status") in {
            "awaiting_customer",
            "customer_responded",
            "customer_no_response",
        }
    ]

    return RecoveryContext(
        invoice=invoice,
        subscription=subscription,
        customer=_customer_context(subscription),
        failure_category=invoice.get(
            "failure_category"
        ),
        raw_gateway_error=(
            latest_failed.get("raw_error_code")
            if latest_failed
            else None
        ),
        failure_reason=(
            latest_failed.get("failure_reason")
            if latest_failed
            else None
        ),
        invoice_amount=int(
            invoice.get("amount") or 0
        ),
        payment_attempts=payment_attempts,
        recovery_actions=recovery_actions,
        retry_count=retry_count,
        time_since_previous_retry_seconds=(
            time_since_previous_retry_seconds
        ),
        previous_recovery_actions=(
            previous_recovery_actions
        ),
        invoice_status=invoice.get("status"),
        customer_action_history=(
            customer_action_history
        ),
        revenue_events=revenue_events,
        audit_history=audit_history,
    )


def get_recovery_context_dict(
    invoice_id: str,
    *,
    as_of: str | datetime | None = None,
) -> dict[str, Any]:
    """Return a recovery context as a plain dictionary."""
    return build_recovery_context(
        invoice_id,
        as_of=as_of,
    ).to_dict()


if __name__ == "__main__":
    from backend.data.db import get_invoices, list_batch_runs

    batches = list_batch_runs(limit=1)

    if not batches:
        print("No batch runs found.")
        raise SystemExit(1)

    invoices = get_invoices(
        batch_id=batches[0]["batch_id"]
    )

    if not invoices:
        print("No invoices found.")
        raise SystemExit(1)

    context = build_recovery_context(
        invoices[0]["invoice_id"]
    )

    print("DUNNFLOW RECOVERY CONTEXT")
    print("=" * 68)
    print(f"Invoice:          {context.invoice['invoice_id']}")
    print(
        f"Subscription:     "
        f"{context.subscription['subscription_id']}"
    )
    print(
        f"Customer:         "
        f"{context.customer.get('customer_id')}"
    )
    print(
        f"Failure category: "
        f"{context.failure_category}"
    )
    print(
        f"Gateway error:    "
        f"{context.raw_gateway_error}"
    )
    print(
        f"Failure reason:   "
        f"{context.failure_reason}"
    )
    print(
        f"Amount:           "
        f"₹{context.invoice_amount / 100:,.2f}"
    )
    print(
        f"Invoice status:   "
        f"{context.invoice_status}"
    )
    print(
        f"Payment attempts: "
        f"{len(context.payment_attempts)}"
    )
    print(
        f"Retry count:      "
        f"{context.retry_count}"
    )
    print(
        f"Recovery actions: "
        f"{len(context.recovery_actions)}"
    )
    print(
        f"Customer actions: "
        f"{len(context.customer_action_history)}"
    )
    print(
        f"Revenue events:   "
        f"{len(context.revenue_events)}"
    )
    print(
        f"Audit entries:    "
        f"{len(context.audit_history)}"
    )
    print(
        f"Time since retry: "
        f"{context.time_since_previous_retry_seconds}"
    )
    print("=" * 68)
