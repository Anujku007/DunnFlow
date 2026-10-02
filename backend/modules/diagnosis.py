"""
DunnFlow diagnosis module.

Responsibility
--------------
Determine WHY a subscription invoice entered revenue recovery.

Input:
    The failed payment attempt associated with an invoice.

Output:
    An actionable failure category plus a human-readable explanation.

Diagnosis does NOT:
    - decide the recovery action
    - execute a payment
    - mark revenue as recovered

Those responsibilities belong to decision_engine.py and execution.py.

Important design principle
--------------------------
The diagnosis source of truth is the FAILED PAYMENT ATTEMPT:

    raw_error_code
    failure_reason

The invoice's failure_category field is only the persisted output of this
module. We never trust a pre-filled category from seed data as the diagnosis.

Unknown failure signals are classified as "unclassified" and routed toward
manual review later. DunnFlow never guesses when it does not understand the
gateway error.
"""

from __future__ import annotations

from backend.data.db import (
    get_invoice,
    get_payment_attempts,
    get_subscription,
    log_audit_entry,
    update_invoice_status,
    update_subscription_status,
)


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

CATEGORY_MAP = {
    "insufficient_fund": "insufficient_funds",
    "insufficient_funds": "insufficient_funds",
    "payment_timed_out": "bank_timeout",
    "authentication_failed": "auth_failed",
    "card_expired": "card_expired",
}


CATEGORY_EXPLANATION = {
    "insufficient_funds": (
        "The customer's account did not have enough available balance "
        "when the recurring charge was attempted."
    ),
    "bank_timeout": (
        "The bank or gateway did not respond within the allowed time, "
        "indicating a likely transient failure."
    ),
    "auth_failed": (
        "The customer authentication or OTP step failed, so customer "
        "action is required rather than blindly retrying."
    ),
    "card_expired": (
        "The payment method associated with the subscription is expired "
        "and must be updated before charging can succeed."
    ),
    "unclassified": (
        "The gateway failure signal is not recognized by DunnFlow. "
        "The system will not guess an automated recovery strategy."
    ),
}


# ---------------------------------------------------------------------------
# Pure classification
# ---------------------------------------------------------------------------

def classify(raw_error_code: str | None) -> str:
    """
    Convert a gateway error code into an actionable failure category.

    Unknown or missing codes intentionally fall back to "unclassified".
    """
    if not raw_error_code:
        return "unclassified"

    return CATEGORY_MAP.get(
        raw_error_code,
        "unclassified",
    )


# ---------------------------------------------------------------------------
# Find source failure attempt
# ---------------------------------------------------------------------------

def get_initial_failed_attempt(invoice_id: str) -> dict | None:
    """
    Return the first failed payment attempt for an invoice.

    The first attempt represents the original failed recurring charge that
    brought the invoice into recovery scope.
    """
    attempts = get_payment_attempts(invoice_id=invoice_id)

    for attempt in attempts:
        if (
            attempt.get("attempt_type") == "initial_charge"
            and attempt.get("result") == "failed"
        ):
            return attempt

    # Defensive fallback: use the first failed attempt if the explicit
    # initial-charge marker is absent.
    for attempt in attempts:
        if attempt.get("result") == "failed":
            return attempt

    return None


# ---------------------------------------------------------------------------
# Diagnose one invoice
# ---------------------------------------------------------------------------

def diagnose_invoice(invoice_id: str) -> dict:
    """
    Diagnose the failed payment associated with one invoice.

    Returns:
        {
            "invoice_id": ...,
            "subscription_id": ...,
            "category": ...,
            "raw_error_code": ...,
            "reason": ...,
            "confidence": ...,
        }
    """

    invoice = get_invoice(invoice_id)

    if not invoice:
        return {
            "invoice_id": invoice_id,
            "subscription_id": None,
            "category": "unclassified",
            "raw_error_code": None,
            "reason": "Invoice not found.",
            "confidence": "none",
        }

    subscription = get_subscription(
        invoice["subscription_id"]
    )

    attempt = get_initial_failed_attempt(invoice_id)

    # ---------------------------------------------------------------
    # No failed payment attempt = cannot safely diagnose.
    # ---------------------------------------------------------------

    if not attempt:
        category = "unclassified"

        reason = (
            "No failed payment attempt was found for this invoice. "
            "DunnFlow will not infer a failure reason without gateway "
            "evidence."
        )

        # Persist safe fallback.
        update_invoice_status(
            invoice_id,
            invoice["status"],
            failure_category=category,
        )

        if subscription:
            update_subscription_status(
                subscription["subscription_id"],
                subscription["status"],
                last_failure_category=category,
            )

        log_audit_entry(
            {
                "batch_id": invoice["batch_id"],
                "subscription_id": invoice["subscription_id"],
                "invoice_id": invoice_id,
                "payment_attempt_id": None,
                "stage": "diagnose",
                "failure_category": category,
                "action_taken": "classified",
                "guardrail_hit": None,
                "result": "flagged",
                "detail": reason,
            }
        )

        return {
            "invoice_id": invoice_id,
            "subscription_id": invoice["subscription_id"],
            "category": category,
            "raw_error_code": None,
            "reason": reason,
            "confidence": "none",
        }

    # ---------------------------------------------------------------
    # Diagnose from actual failure signal
    # ---------------------------------------------------------------

    raw_error_code = attempt.get("raw_error_code")
    failure_reason = attempt.get("failure_reason")

    category = classify(raw_error_code)

    explanation = CATEGORY_EXPLANATION[category]

    if category == "unclassified":
        result = "flagged"
    else:
        result = "diagnosed"

    detail = (
        f"Gateway signal raw_error_code='{raw_error_code}' "
        f"classified as '{category}'. "
        f"Gateway reason: '{failure_reason}'. "
        f"Diagnosis: {explanation}"
    )

    # ---------------------------------------------------------------
    # Persist diagnosis result
    # ---------------------------------------------------------------

    update_invoice_status(
        invoice_id,
        invoice["status"],
        failure_category=category,
    )

    if subscription:
        update_subscription_status(
            subscription["subscription_id"],
            subscription["status"],
            last_failure_category=category,
        )

    # ---------------------------------------------------------------
    # Audit the diagnosis
    # ---------------------------------------------------------------

    log_audit_entry(
        {
            "batch_id": invoice["batch_id"],
            "subscription_id": invoice["subscription_id"],
            "invoice_id": invoice_id,
            "payment_attempt_id": attempt["attempt_id"],
            "stage": "diagnose",
            "failure_category": category,
            "action_taken": "classified",
            "guardrail_hit": None,
            "result": result,
            "detail": detail,
        }
    )

    return {
        "invoice_id": invoice_id,
        "subscription_id": invoice["subscription_id"],
        "category": category,
        "raw_error_code": raw_error_code,
        "reason": explanation,
        "confidence": "deterministic",
        "payment_attempt_id": attempt["attempt_id"],
    }


# ---------------------------------------------------------------------------
# Batch diagnosis
# ---------------------------------------------------------------------------

def diagnose_batch(batch_id: str) -> dict:
    """
    Diagnose every detected invoice in a batch.

    Detection and diagnosis remain separate stages:

        detection → identifies what is at risk
        diagnosis → identifies why it is at risk
    """

    from backend.data.db import get_invoices

    invoices = get_invoices(batch_id=batch_id)

    diagnosed: list[dict] = []
    counts: dict[str, int] = {}

    for invoice in invoices:
        # Only invoices currently in recovery scope should be diagnosed.
        if invoice["status"] != "issued":
            continue

        result = diagnose_invoice(
            invoice["invoice_id"]
        )

        diagnosed.append(result)

        category = result["category"]

        counts[category] = counts.get(category, 0) + 1

    return {
        "batch_id": batch_id,
        "diagnosed_count": len(diagnosed),
        "category_counts": counts,
        "results": diagnosed,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from backend.data.db import list_batch_runs

    batches = list_batch_runs(limit=1)

    if not batches:
        print("No batch runs found.")
        raise SystemExit(1)

    batch_id = batches[0]["batch_id"]

    report = diagnose_batch(batch_id)

    print()
    print("=" * 64)
    print("DUNNFLOW DIAGNOSIS")
    print("=" * 64)
    print(f"Batch ID:             {batch_id}")
    print(f"Diagnosed invoices:   {report['diagnosed_count']}")
    print()

    print("Diagnosis distribution:")

    for category, count in report["category_counts"].items():
        print(f"  {category:<22} {count}")

    print("=" * 64)