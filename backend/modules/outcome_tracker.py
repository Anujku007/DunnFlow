"""
DunnFlow outcome tracker.

Responsibility
--------------
Reconcile the complete recovery history of an invoice into ONE canonical
outcome.

Possible outcomes:

    recovered
    in_progress
    exhausted
    blocked
    manual_review

The outcome tracker DOES NOT:
    - make a new recovery decision
    - execute a payment
    - send a customer message
    - create revenue

It only interprets the state already recorded by previous pipeline stages.

Financial truth
---------------
A case is considered financially recovered ONLY when a
`recovery_confirmed` revenue event exists.

This prevents:
    message sent      != recovered
    action scheduled  != recovered
    payment attempted != recovered
    invoice paid       = recovered

Auditability
------------
Each invoice receives one canonical final-outcome audit entry.

Repeated execution is idempotent: if the same outcome is already recorded,
another duplicate outcome entry is not created.
"""

from __future__ import annotations

from backend.data.db import (
    get_audit_log,
    get_batch_metrics,
    get_invoice,
    get_invoices,
    get_payment_attempts,
    get_recovery_actions,
    get_revenue_events,
    get_subscription,
    log_audit_entry,
)


# ============================================================================
# OUTCOME TYPES
# ============================================================================

OUTCOME_RECOVERED = "recovered"
OUTCOME_IN_PROGRESS = "in_progress"
OUTCOME_EXHAUSTED = "exhausted"
OUTCOME_BLOCKED = "blocked"
OUTCOME_MANUAL_REVIEW = "manual_review"
OUTCOME_NOT_FOUND = "not_found"


MAX_AUTOMATED_PAYMENT_RETRIES = 3


# ============================================================================
# HELPERS
# ============================================================================

def _money(paise: int) -> str:
    """Format paise as INR."""
    return f"₹{paise / 100:,.2f}"


def _automated_retry_count(invoice_id: str) -> int:
    """
    Count DunnFlow recovery payment attempts.

    The original subscription charge is NOT counted.
    """
    attempts = get_payment_attempts(
        invoice_id=invoice_id
    )

    return sum(
        1
        for attempt in attempts
        if attempt.get("attempt_type") in {
            "auto_retry",
            "manual_retry",
            "recovery_payment",
        }
    )


def _recovery_confirmed_event(
    invoice_id: str,
) -> dict | None:
    """
    Return the authoritative recovery-confirmed event, if one exists.
    """
    events = get_revenue_events(
        invoice_id=invoice_id,
        event_type="recovery_confirmed",
    )

    if not events:
        return None

    return events[-1]


def _has_blocked_action(
    invoice_id: str,
) -> dict | None:
    """
    Return the most recent blocked recovery action, if present.
    """
    actions = get_recovery_actions(
        invoice_id=invoice_id
    )

    blocked = [
        action
        for action in actions
        if action.get("status") == "blocked"
    ]

    if not blocked:
        return None

    return blocked[-1]


def _has_manual_review_action(
    invoice_id: str,
) -> bool:
    """
    Return True when the invoice was routed to manual review.
    """
    actions = get_recovery_actions(
        invoice_id=invoice_id
    )

    return any(
        action.get("action_type") == "manual_review"
        for action in actions
    )


def _find_previous_final_outcome(
    invoice_id: str,
) -> dict | None:
    """
    Find the most recent canonical final-outcome audit entry.

    Final outcome entries are identified by:

        stage = outcome
        action_taken = finalize_outcome
    """
    entries = get_audit_log(
        invoice_id=invoice_id
    )

    final_entries = [
        entry
        for entry in entries
        if entry.get("stage") == "outcome"
        and entry.get("action_taken") == "finalize_outcome"
    ]

    if not final_entries:
        return None

    return final_entries[-1]


# ============================================================================
# OUTCOME DETERMINATION
# ============================================================================

def determine_outcome(
    invoice_id: str,
) -> dict:
    """
    Determine the canonical outcome for one invoice.

    Outcome priority:

        1. recovered
        2. manual_review
        3. blocked
        4. exhausted
        5. in_progress

    Recovery always wins because once money has been verified as recovered,
    an earlier blocked/pending state is no longer the final outcome.
    """

    invoice = get_invoice(
        invoice_id
    )

    if not invoice:
        return {
            "invoice_id": invoice_id,
            "outcome": OUTCOME_NOT_FOUND,
            "amount": 0,
            "recovered_amount": 0,
            "detail": "Invoice does not exist.",
        }

    subscription = get_subscription(
        invoice["subscription_id"]
    )

    recovery_event = _recovery_confirmed_event(
        invoice_id
    )

    # ------------------------------------------------------------------
    # 1. RECOVERED
    # ------------------------------------------------------------------

    if recovery_event:

        recovered_amount = int(
            recovery_event.get("amount", 0)
        )

        attempts = get_payment_attempts(
            invoice_id=invoice_id
        )

        successful_attempt = next(
            (
                attempt
                for attempt in attempts
                if attempt.get("result") == "success"
                and attempt.get("attempt_type") in {
                    "auto_retry",
                    "manual_retry",
                    "recovery_payment",
                    "customer_payment",
                }
            ),
            None,
        )

        recovery_attempt_number = None

        if successful_attempt:
            recovery_attempts_before = sum(
                1
                for attempt in attempts
                if attempt.get("attempt_id") is not None
                and attempt.get("attempt_number", 0)
                <= successful_attempt.get(
                    "attempt_number",
                    0,
                )
                and attempt.get("attempt_type") in {
                    "auto_retry",
                    "manual_retry",
                    "recovery_payment",
                }
            )

            # Customer payment is outside the automated retry budget.
            if successful_attempt.get("attempt_type") == "customer_payment":
                recovery_attempt_number = None
            else:
                recovery_attempt_number = (
                    recovery_attempts_before
                )

        if recovery_attempt_number is not None:
            attempt_text = (
                f"DunnFlow recovery attempt "
                f"#{recovery_attempt_number}."
            )
        else:
            attempt_text = (
                "customer-driven payment recovery."
            )

        customer_name = (
            subscription.get("customer_name")
            if subscription
            else "customer"
        ) or "customer"

        detail = (
            f"Recovered {_money(recovered_amount)} from "
            f"{customer_name}. "
            f"Invoice {invoice_id} is paid. "
            f"{attempt_text}"
        )

        return {
            "invoice_id": invoice_id,
            "subscription_id": invoice[
                "subscription_id"
            ],
            "batch_id": invoice[
                "batch_id"
            ],
            "outcome": OUTCOME_RECOVERED,
            "amount": int(invoice["amount"]),
            "recovered_amount": recovered_amount,
            "recovery_event_id": recovery_event.get(
                "event_id"
            ),
            "detail": detail,
        }

    # ------------------------------------------------------------------
    # 2. MANUAL REVIEW
    # ------------------------------------------------------------------

    if (
        invoice.get("failure_category") == "unclassified"
        or _has_manual_review_action(invoice_id)
    ):

        detail = (
            f"Manual review required for invoice "
            f"{invoice_id}. "
            f"Revenue at risk: {_money(int(invoice['amount']))}. "
            "DunnFlow did not automate an unknown failure condition."
        )

        return {
            "invoice_id": invoice_id,
            "subscription_id": invoice[
                "subscription_id"
            ],
            "batch_id": invoice[
                "batch_id"
            ],
            "outcome": OUTCOME_MANUAL_REVIEW,
            "amount": int(invoice["amount"]),
            "recovered_amount": 0,
            "detail": detail,
        }

    # ------------------------------------------------------------------
    # 3. BLOCKED
    # ------------------------------------------------------------------

    blocked_action = _has_blocked_action(
        invoice_id
    )

    if blocked_action:

        guardrail = (
            blocked_action.get("guardrail_hit")
            or "automated_recovery_blocked"
        )

        detail = (
            f"Automated recovery blocked for invoice "
            f"{invoice_id}. "
            f"Reason: {guardrail}. "
            f"Revenue still at risk: "
            f"{_money(int(invoice['amount']))}."
        )

        return {
            "invoice_id": invoice_id,
            "subscription_id": invoice[
                "subscription_id"
            ],
            "batch_id": invoice[
                "batch_id"
            ],
            "outcome": OUTCOME_BLOCKED,
            "amount": int(invoice["amount"]),
            "recovered_amount": 0,
            "guardrail_hit": guardrail,
            "detail": detail,
        }

    # ------------------------------------------------------------------
    # 4. EXHAUSTED
    # ------------------------------------------------------------------

    retry_count = _automated_retry_count(
        invoice_id
    )

    if (
        retry_count >= MAX_AUTOMATED_PAYMENT_RETRIES
        or (
            subscription
            and subscription.get("status") == "halted"
        )
    ):

        detail = (
            f"Recovery exhausted for invoice "
            f"{invoice_id}. "
            f"{retry_count}/"
            f"{MAX_AUTOMATED_PAYMENT_RETRIES} "
            "automated recovery attempts were used. "
            f"Revenue still at risk: "
            f"{_money(int(invoice['amount']))}. "
            "Subscription recovery must now be handled outside "
            "the automated retry budget."
        )

        return {
            "invoice_id": invoice_id,
            "subscription_id": invoice[
                "subscription_id"
            ],
            "batch_id": invoice[
                "batch_id"
            ],
            "outcome": OUTCOME_EXHAUSTED,
            "amount": int(invoice["amount"]),
            "recovered_amount": 0,
            "retry_count": retry_count,
            "detail": detail,
        }

    # ------------------------------------------------------------------
    # 5. IN PROGRESS
    # ------------------------------------------------------------------

    detail = (
        f"Recovery remains in progress for invoice "
        f"{invoice_id}. "
        f"Revenue still at risk: "
        f"{_money(int(invoice['amount']))}. "
        "A future retry or customer action remains possible."
    )

    return {
        "invoice_id": invoice_id,
        "subscription_id": invoice[
            "subscription_id"
        ],
        "batch_id": invoice[
            "batch_id"
        ],
        "outcome": OUTCOME_IN_PROGRESS,
        "amount": int(invoice["amount"]),
        "recovered_amount": 0,
        "retry_count": retry_count,
        "detail": detail,
    }


# ============================================================================
# AUDIT
# ============================================================================

def _persist_final_outcome(
    outcome: dict,
) -> None:
    """
    Write one canonical outcome audit entry.

    Idempotency rule:
        If the most recent final-outcome audit entry already has the same
        outcome and detail, do not create another entry.
    """

    invoice_id = outcome["invoice_id"]

    previous = _find_previous_final_outcome(
        invoice_id
    )

    if previous:
        same_outcome = (
            previous.get("result")
            == outcome["outcome"]
        )

        same_detail = (
            previous.get("detail")
            == outcome["detail"]
        )

        if same_outcome and same_detail:
            return

    log_audit_entry(
        {
            "batch_id": outcome["batch_id"],
            "subscription_id": outcome.get(
                "subscription_id"
            ),
            "invoice_id": invoice_id,
            "payment_attempt_id": None,
            "stage": "outcome",
            "failure_category": None,
            "action_taken": "finalize_outcome",
            "guardrail_hit": outcome.get(
                "guardrail_hit"
            ),
            "result": outcome["outcome"],
            "detail": outcome["detail"],
        }
    )


# ============================================================================
# ONE INVOICE
# ============================================================================

def summarize_invoice_outcome(
    invoice_id: str,
) -> dict:
    """
    Determine and persist the canonical outcome for one invoice.
    """

    outcome = determine_outcome(
        invoice_id
    )

    if outcome["outcome"] != OUTCOME_NOT_FOUND:
        _persist_final_outcome(
            outcome
        )

    return outcome


# ============================================================================
# BATCH
# ============================================================================

def summarize_batch_outcomes(
    batch_id: str,
) -> dict:
    """
    Reconcile every invoice in a batch.

    Returns:
        batch-level outcome counts and individual summaries.
    """

    invoices = get_invoices(
        batch_id=batch_id
    )

    outcomes = []

    counts = {
        OUTCOME_RECOVERED: 0,
        OUTCOME_IN_PROGRESS: 0,
        OUTCOME_EXHAUSTED: 0,
        OUTCOME_BLOCKED: 0,
        OUTCOME_MANUAL_REVIEW: 0,
    }

    for invoice in invoices:

        outcome = summarize_invoice_outcome(
            invoice["invoice_id"]
        )

        outcomes.append(
            outcome
        )

        outcome_type = outcome[
            "outcome"
        ]

        if outcome_type in counts:
            counts[outcome_type] += 1

    metrics = get_batch_metrics(
        batch_id
    )

    return {
        "batch_id": batch_id,
        "total_invoices": len(invoices),
        "outcome_counts": counts,
        "outcomes": outcomes,
        "metrics": metrics,
    }


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":

    from backend.data.db import list_batch_runs

    batches = list_batch_runs(
        limit=1
    )

    if not batches:
        print(
            "No batch runs found."
        )
        raise SystemExit(1)

    batch_id = batches[0][
        "batch_id"
    ]

    report = summarize_batch_outcomes(
        batch_id
    )

    metrics = report[
        "metrics"
    ]

    print()
    print("=" * 70)
    print("DUNNFLOW OUTCOME RECONCILIATION")
    print("=" * 70)

    print(
        f"Batch ID:              "
        f"{batch_id}"
    )

    print(
        f"Total invoices:        "
        f"{report['total_invoices']}"
    )

    print()
    print("Final outcomes:")

    for outcome, count in report[
        "outcome_counts"
    ].items():

        print(
            f"  {outcome:<20} "
            f"{count}"
        )

    print()
    print("Financial result:")

    print(
        f"  Amount at risk:      "
        f"₹{metrics['amount_at_risk'] / 100:,.2f}"
    )

    print(
        f"  Amount recovered:    "
        f"₹{metrics['amount_recovered'] / 100:,.2f}"
    )

    print(
        f"  Recovery rate:       "
        f"{metrics['recovery_rate_pct']}%"
    )

    print()
    print(
        "Outcome reconciliation: "
        f"{metrics['outcome_count_total']} / "
        f"{metrics['total_invoices']}"
    )

    print(
        "Reconciled:            "
        f"{metrics['outcome_count_matches_invoice_count']}"
    )

    print("=" * 70)