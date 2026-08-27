"""
Outcome tracker for DunnFlow.

execution.py already updates a payment's status after each individual
attempt (recovered / pending_retry / exhausted) and logs a per-attempt
audit entry. outcome_tracker.py's job is different: it's the reconciliation
layer that looks at a payment's FULL attempt history and writes one final,
human-readable "outcome" audit entry summarizing what ultimately happened —
this is the entry your Audit Trail UI highlights for each customer, and it's
what your final pitch-video metrics story is built from.

Keeping this separate from execution.py matters because:
  - execution.py only knows about the attempt it just made
  - outcome_tracker.py can look across the whole retry_attempts history and
    say something like "recovered on attempt 2 of 3" or "exhausted after
    3 attempts, final category: insufficient_funds" — the kind of statement
    you want in your final report, not scattered across raw log rows.
"""

from backend.data.db import (
    get_payment,
    get_retry_attempts,
    get_failed_payments,
    log_audit_entry,
)


def summarize_payment_outcome(payment_id: str) -> dict:
    """
    Look at a payment's current status + full attempt history and produce
    a single reconciled outcome summary. Writes one audit entry capturing
    the final state in plain language.
    """
    payment = get_payment(payment_id)
    if not payment:
        return {"payment_id": payment_id, "outcome": "not_found"}

    attempts = get_retry_attempts(payment_id)
    status = payment["status"]

    if status == "recovered":
        successful_attempt = next((a for a in attempts if a["result"] in ("success",)), None)
        attempt_no = successful_attempt["attempt_number"] if successful_attempt else payment["retry_count"]
        detail = (
            f"Recovered ₹{payment['amount']/100:.2f} from {payment['customer_name']} "
            f"on attempt {attempt_no} of {len(attempts)}. "
            f"Original failure: {payment['failure_category']}."
        )
        outcome = "recovered"

    elif status == "exhausted":
        detail = (
            f"Failed to recover ₹{payment['amount']/100:.2f} from "
            f"{payment['customer_name']} after {len(attempts)} attempts "
            f"(guardrail limit reached). Original failure: "
            f"{payment['failure_category']}. Recommend manual follow-up."
        )
        outcome = "exhausted"

    elif status == "pending_retry":
        detail = (
            f"Recovery still in progress for {payment['customer_name']} — "
            f"{len(attempts)} attempt(s) so far, awaiting next scheduled "
            f"action or customer response. Original failure: "
            f"{payment['failure_category']}."
        )
        outcome = "in_progress"

    else:  # 'failed' — no attempts made yet (e.g. still manual_review or untouched)
        detail = (
            f"No recovery action taken yet for {payment['customer_name']} "
            f"(status: {status}). Failure category: "
            f"{payment.get('failure_category') or 'not yet diagnosed'}."
        )
        outcome = "untouched"

    log_audit_entry({
        "payment_id": payment_id,
        "customer_id": payment["customer_id"],
        "stage": "outcome",
        "failure_category": payment.get("failure_category"),
        "action_taken": "summarize",
        "guardrail_hit": None,
        "result": outcome,
        "detail": detail,
    })

    return {
        "payment_id": payment_id,
        "outcome": outcome,
        "attempts_made": len(attempts),
        "amount": payment["amount"],
        "detail": detail,
    }


def summarize_all_outcomes() -> list[dict]:
    """Run outcome summarization across every payment currently in the DB.
    Typically called at the end of an orchestrator batch run, right before
    generating the final metrics report."""
    all_payments = get_failed_payments()
    return [summarize_payment_outcome(p["payment_id"]) for p in all_payments]


if __name__ == "__main__":
    results = summarize_all_outcomes()
    counts = {}
    for r in results:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    print("Outcome summary:", counts)