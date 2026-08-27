"""
Detection module for DunnFlow.

Responsibility
--------------
Identify revenue that is currently at risk and eligible for recovery.

Detection does NOT:
    - diagnose the failure
    - choose a recovery action
    - execute a payment
    - mark revenue as recovered

Those responsibilities belong to later stages of the pipeline.

Detection is batch-scoped so that every benchmark/demo run has an explicit
and reproducible set of recovery opportunities.

Current eligibility rule
------------------------
An invoice is considered at risk when:

    invoice.status == "issued"
    AND
    subscription.status == "pending"

This mirrors the important subscription-recovery state represented in the
DunnFlow benchmark: a recurring charge failed, the invoice remains unpaid,
and the subscription requires recovery handling.

All detected opportunities are written to the audit log.
"""

from __future__ import annotations

from backend.data.db import (
    get_invoices,
    get_subscription,
    log_audit_entry,
)


# ---------------------------------------------------------------------------
# Detection rules
# ---------------------------------------------------------------------------

ELIGIBLE_INVOICE_STATUS = "issued"
ELIGIBLE_SUBSCRIPTION_STATUS = "pending"


# ---------------------------------------------------------------------------
# Single-invoice detection
# ---------------------------------------------------------------------------

def detect_invoice(invoice: dict) -> dict:
    """
    Determine whether one invoice is currently a revenue-recovery
    opportunity.

    Returns:
        {
            "invoice_id": str,
            "subscription_id": str,
            "eligible": bool,
            "amount_at_risk": int,
            "reason": str,
        }
    """

    invoice_id = invoice["invoice_id"]
    subscription_id = invoice["subscription_id"]

    subscription = get_subscription(subscription_id)

    if not subscription:
        result = {
            "invoice_id": invoice_id,
            "subscription_id": subscription_id,
            "eligible": False,
            "amount_at_risk": 0,
            "reason": (
                "Invoice references a subscription that does not exist."
            ),
        }

        return result

    # ---------------------------------------------------------------
    # Rule 1: invoice must still be unpaid / issued
    # ---------------------------------------------------------------

    if invoice["status"] != ELIGIBLE_INVOICE_STATUS:
        return {
            "invoice_id": invoice_id,
            "subscription_id": subscription_id,
            "eligible": False,
            "amount_at_risk": 0,
            "reason": (
                f"Invoice status is '{invoice['status']}', not "
                f"'{ELIGIBLE_INVOICE_STATUS}'."
            ),
        }

    # ---------------------------------------------------------------
    # Rule 2: subscription must require recovery
    # ---------------------------------------------------------------

    if subscription["status"] != ELIGIBLE_SUBSCRIPTION_STATUS:
        return {
            "invoice_id": invoice_id,
            "subscription_id": subscription_id,
            "eligible": False,
            "amount_at_risk": 0,
            "reason": (
                f"Subscription status is '{subscription['status']}', not "
                f"'{ELIGIBLE_SUBSCRIPTION_STATUS}'."
            ),
        }

    # ---------------------------------------------------------------
    # Eligible recovery opportunity
    # ---------------------------------------------------------------

    amount = int(invoice["amount"])

    return {
        "invoice_id": invoice_id,
        "subscription_id": subscription_id,
        "eligible": True,
        "amount_at_risk": amount,
        "reason": (
            "Unpaid invoice attached to a pending subscription; "
            "revenue is eligible for recovery."
        ),
    }


# ---------------------------------------------------------------------------
# Batch detection
# ---------------------------------------------------------------------------

def detect_batch(batch_id: str) -> dict:
    """
    Detect all revenue-at-risk invoices in one batch.

    Returns a batch-level detection report:

        {
            "batch_id": ...,
            "detected_count": ...,
            "amount_at_risk": ...,
            "opportunities": [...],
            "excluded_count": ...
        }

    Detection is intentionally read-only with respect to financial state.
    It only records audit events; it does not recover or mutate invoices.
    """

    invoices = get_invoices(batch_id=batch_id)

    opportunities: list[dict] = []
    excluded_count = 0

    for invoice in invoices:
        result = detect_invoice(invoice)

        subscription = get_subscription(
            invoice["subscription_id"]
        )

        if result["eligible"]:
            opportunities.append(
                {
                    "invoice_id": invoice["invoice_id"],
                    "subscription_id": invoice["subscription_id"],
                    "customer_id": (
                        subscription["customer_id"]
                        if subscription
                        else None
                    ),
                    "customer_name": (
                        subscription["customer_name"]
                        if subscription
                        else None
                    ),
                    "amount": invoice["amount"],
                    "currency": invoice["currency"],
                    "failure_category": invoice.get(
                        "failure_category"
                    ),
                    "reason": result["reason"],
                }
            )

            # -------------------------------------------------------
            # Audit: detected recovery opportunity
            # -------------------------------------------------------

            log_audit_entry(
                {
                    "batch_id": batch_id,
                    "subscription_id": invoice["subscription_id"],
                    "invoice_id": invoice["invoice_id"],
                    "stage": "detect",
                    "failure_category": invoice.get(
                        "failure_category"
                    ),
                    "action_taken": "recovery_candidate_detected",
                    "guardrail_hit": None,
                    "result": "eligible",
                    "detail": (
                        f"Detected ₹{invoice['amount'] / 100:,.2f} "
                        f"revenue at risk on invoice "
                        f"{invoice['invoice_id']}. "
                        f"{result['reason']}"
                    ),
                }
            )

        else:
            excluded_count += 1

            # -------------------------------------------------------
            # Audit excluded records too.
            #
            # This matters for explainability:
            # the system should be able to explain not only what it
            # acted on, but why another record was left alone.
            # -------------------------------------------------------

            log_audit_entry(
                {
                    "batch_id": batch_id,
                    "subscription_id": invoice["subscription_id"],
                    "invoice_id": invoice["invoice_id"],
                    "stage": "detect",
                    "failure_category": invoice.get(
                        "failure_category"
                    ),
                    "action_taken": "none",
                    "guardrail_hit": None,
                    "result": "excluded",
                    "detail": (
                        f"Invoice {invoice['invoice_id']} was not "
                        f"selected for automated recovery. "
                        f"Reason: {result['reason']}"
                    ),
                }
            )

    amount_at_risk = sum(
        opportunity["amount"]
        for opportunity in opportunities
    )

    return {
        "batch_id": batch_id,
        "detected_count": len(opportunities),
        "amount_at_risk": amount_at_risk,
        "excluded_count": excluded_count,
        "opportunities": opportunities,
    }


# ---------------------------------------------------------------------------
# Convenience helper
# ---------------------------------------------------------------------------

def detect_revenue_at_risk(batch_id: str) -> dict:
    """
    Public entry point used by the orchestrator.

    This name makes the intent explicit for the agent pipeline.
    """
    return detect_batch(batch_id)


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from backend.data.db import list_batch_runs

    batches = list_batch_runs(limit=1)

    if not batches:
        print("No batch runs found.")
        raise SystemExit(1)

    batch_id = batches[0]["batch_id"]

    report = detect_revenue_at_risk(batch_id)

    print()
    print("=" * 64)
    print("DUNNFLOW DETECTION")
    print("=" * 64)
    print(f"Batch ID:             {report['batch_id']}")
    print(f"Detected invoices:    {report['detected_count']}")
    print(
        f"Amount at risk:       "
        f"₹{report['amount_at_risk'] / 100:,.2f}"
    )
    print(f"Excluded:             {report['excluded_count']}")
    print("=" * 64)