"""
Orchestrator for DunnFlow.

This is the single entrypoint that ties every module together into the
full pipeline the buildathon track asks for:

    detect -> diagnose -> decide -> execute -> track outcome -> audit

It's intentionally thin — no business logic lives here, it just calls each
module in the right order and returns a batch-level summary. This is also
what the API's POST /api/run-batch endpoint calls, and what your demo
video's "click Run Batch" moment triggers live.

Design choice: each payment moves through the full pipeline one at a time
(detect -> diagnose -> decide -> execute -> track) rather than running each
stage as a separate pass over all payments. This keeps the per-payment audit
trail chronologically coherent (all of one customer's log entries happen
together), which is easier to read and demo than interleaved batch stages.
"""

from backend.data.db import init_db, get_failed_payments, log_audit_entry
from backend.modules.diagnosis import diagnose_payment
from backend.modules.decision_engine import decide
from backend.modules.execution import execute
from backend.modules.outcome_tracker import summarize_payment_outcome
from backend.reports.metrics import get_metrics_report


def run_pipeline_for_payment(payment: dict) -> dict:
    """Run one payment through the full pipeline. Returns a per-payment result."""
    log_audit_entry({
        "payment_id": payment["payment_id"],
        "customer_id": payment["customer_id"],
        "stage": "detect",
        "failure_category": None,
        "action_taken": "none",
        "guardrail_hit": None,
        "result": "n/a",
        "detail": f"Detected failed payment: raw_error_code="
                  f"'{payment['raw_error_code']}', amount=₹{payment['amount']/100:.2f}.",
    })

    # 1. Diagnose (skip if already diagnosed — pipeline is idempotent)
    if not payment.get("failure_category"):
        payment = diagnose_payment(payment)

    # 2. Decide
    decision = decide(payment)

    # 3. Execute — only if the decision engine actually scheduled an action
    execution_result = None
    if decision["decision"] == "scheduled":
        execution_result = execute(decision)

    # 4. Track outcome (always — even manual_review/blocked payments get a
    #    reconciled outcome entry so nothing falls through silently)
    outcome = summarize_payment_outcome(payment["payment_id"])

    return {
        "payment_id": payment["payment_id"],
        "decision": decision["decision"],
        "action_type": decision.get("action_type"),
        "execution_result": execution_result,
        "outcome": outcome["outcome"],
    }


def run_batch(status_filter: str = "failed") -> dict:
    """
    Run the full pipeline across every payment matching status_filter
    (default: only untouched failed payments — so re-running a batch
    doesn't reprocess already-recovered/exhausted payments).

    Returns a batch-level summary dict, ready to hand straight to the API
    layer / UI, plus the final metrics report.
    """
    init_db()
    payments = get_failed_payments(status=status_filter)

    results = [run_pipeline_for_payment(p) for p in payments]

    decision_counts = {}
    outcome_counts = {}
    for r in results:
        decision_counts[r["decision"]] = decision_counts.get(r["decision"], 0) + 1
        outcome_counts[r["outcome"]] = outcome_counts.get(r["outcome"], 0) + 1

    return {
        "processed": len(results),
        "decision_counts": decision_counts,
        "outcome_counts": outcome_counts,
        "results": results,
        "metrics": get_metrics_report(),
    }


if __name__ == "__main__":
    summary = run_batch()
    print(f"Processed {summary['processed']} payments.")
    print("Decisions:", summary["decision_counts"])
    print("Outcomes:", summary["outcome_counts"])
    print("Metrics:", summary["metrics"])