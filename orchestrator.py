"""
DunnFlow Autonomous Recovery Orchestrator.

Single entrypoint for the current invoice/subscription recovery pipeline:

    detect
        ->
    decide
        ->
    schedule
        ->
    execute due actions
        ->
    customer response
        ->
    outcome reconciliation
        ->
    metrics

The orchestrator contains no recovery business logic.
It only coordinates the existing modules.
"""

from __future__ import annotations

from backend.data.db import (
    init_db,
    get_batch_run,
    get_batch_metrics,
)

from backend.modules.detection import (
    detect_revenue_at_risk,
)

from backend.modules.decision_engine import (
    decide_batch,
)

from backend.modules.scheduler import (
    schedule_batch,
)

from backend.modules.execution import (
    execute_due_actions,
)

from backend.modules.customer_response import (
    process_customer_responses,
)

from backend.modules.outcome_tracker import (
    summarize_batch_outcomes,
)


def run_batch(
    batch_id: str,
    *,
    as_of=None,
) -> dict:
    """
    Run one batch through the complete DunnFlow recovery pipeline.

    Pipeline:

        detect
        -> decide
        -> schedule
        -> execute due actions
        -> customer response
        -> outcome reconciliation
        -> metrics

    Args:
        batch_id:
            Existing DunnFlow batch to process.

        as_of:
            Optional virtual/current timestamp used by the scheduler
            and execution layer. When omitted, the system uses the
            actual current time.

    Returns:
        Complete batch-level orchestration report.
    """

    init_db()

    batch = get_batch_run(batch_id)

    if not batch:
        raise ValueError(
            f"Batch '{batch_id}' does not exist."
        )

    # ================================================================
    # 1. DETECT
    # ================================================================

    detection = detect_revenue_at_risk(
        batch_id
    )

    # ================================================================
    # 2. DECIDE
    # ================================================================

    decisions = decide_batch(
        batch_id,
        as_of=as_of,
    )

    # ================================================================
    # 3. SCHEDULE
    # ================================================================

    schedule = schedule_batch(
        batch_id,
        as_of=as_of,
    )

    # ================================================================
    # 4. EXECUTE ONLY DUE ACTIONS
    # ================================================================

    execution = execute_due_actions(
        batch_id,
        as_of=as_of,
    )

    # ================================================================
    # 5. CUSTOMER RESPONSE
    # ================================================================

    customer_response = process_customer_responses(
        batch_id
    )

    # ================================================================
    # 6. FINAL OUTCOME RECONCILIATION
    # ================================================================

    outcomes = summarize_batch_outcomes(
        batch_id
    )

    # ================================================================
    # 7. FINAL SOURCE-OF-TRUTH METRICS
    # ================================================================

    metrics = get_batch_metrics(
        batch_id
    )

    return {
        "batch_id": batch_id,
        "pipeline": [
            "detect",
            "decide",
            "schedule",
            "execute",
            "customer_response",
            "outcome",
            "metrics",
        ],
        "detection": detection,
        "decisions": decisions,
        "schedule": schedule,
        "execution": execution,
        "customer_response": customer_response,
        "outcomes": outcomes,
        "metrics": metrics,
    }


if __name__ == "__main__":
    import sys
    import pprint

    if len(sys.argv) != 2:
        print(
            "Usage: python orchestrator.py <batch_id>"
        )
        raise SystemExit(1)

    batch_id = sys.argv[1]

    report = run_batch(
        batch_id
    )

    pprint.pp(
        report
    )