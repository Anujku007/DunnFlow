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

from backend.ai.ai_policy_reconciliation import (
    reconcile_invoice,
)
from backend.ai.recovery_advisor import (
    RecoveryAdvisor,
)


def run_batch(
    batch_id: str,
    *,
    as_of=None,
    ai_advisor: RecoveryAdvisor | None = None,
) -> dict:
    """
    Run one batch through the complete DunnFlow recovery pipeline.

    The benchmark uses the deterministic demo clock:

        now
        -> one_hour
        -> one_day

    Decisions are created once. Execution is then advanced through the
    virtual timeline so scheduled actions can become due without waiting
    in real time.
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
    # 2. DECIDE ONCE
    # ================================================================

    decisions = decide_batch(
        batch_id,
        as_of=as_of,
    )

    # ================================================================
    # 3. AI ADVISORY RECONCILIATION
    # ================================================================
    #
    # AI observes each deterministic decision and provides advisory
    # intelligence. It does NOT authorize, modify, schedule, or
    # execute the recovery action.
    #
    # The deterministic decision remains the sole authority for
    # downstream scheduling and execution.
    #
    # Passing ai_advisor explicitly enables controlled AI integration
    # tests without forcing live provider calls during normal runs.
    # ================================================================

    ai_reconciliation = {
        "enabled": ai_advisor is not None,
        "checked": 0,
        "agreements": 0,
        "disagreements": 0,
        "ai_unavailable": 0,
        "results": [],
    }

    if ai_advisor is not None:
        for deterministic_decision in decisions["decisions"]:
            reconciliation = reconcile_invoice(
                invoice_id=deterministic_decision["invoice_id"],
                deterministic_decision=deterministic_decision,
                advisor=ai_advisor,
                as_of=as_of,
            )

            ai_reconciliation["checked"] += 1
            ai_reconciliation["results"].append(
                reconciliation.to_dict()
            )

            if reconciliation.result == "agreement":
                ai_reconciliation["agreements"] += 1

            elif reconciliation.result == "disagreement":
                ai_reconciliation["disagreements"] += 1

            elif reconciliation.result == "ai_unavailable":
                ai_reconciliation["ai_unavailable"] += 1

    # ================================================================
    # 4. GET DETERMINISTIC DEMO CLOCK
    # ================================================================

    from backend.modules.scheduler import (
        get_batch_demo_timestamps,
        schedule_batch,
    )

    demo_times = get_batch_demo_timestamps(
        batch_id
    )

    # ================================================================
    # 5. SCHEDULE AT T0
    # ================================================================

    schedule_now = schedule_batch(
        batch_id,
        as_of=(
            as_of
            if as_of is not None
            else demo_times["now"]
        ),
    )

    # ================================================================
    # 6. EXECUTE AT ONE-HOUR STAGE
    # ================================================================

    execution_one_hour = execute_due_actions(
        batch_id,
        as_of=demo_times["one_hour"],
    )

    # ================================================================
    # 7. EXECUTE AT ONE-DAY STAGE
    # ================================================================

    execution_one_day = execute_due_actions(
        batch_id,
        as_of=demo_times["one_day"],
    )

    # ================================================================
    # 8. CUSTOMER RESPONSE
    # ================================================================

    customer_response = process_customer_responses(
        batch_id
    )

    # ================================================================
    # 9. FINAL OUTCOME RECONCILIATION
    # ================================================================

    outcomes = summarize_batch_outcomes(
        batch_id
    )

    # ================================================================
    # 10. FINAL SOURCE-OF-TRUTH METRICS
    # ================================================================

    metrics = get_batch_metrics(
        batch_id
    )

    return {
        "batch_id": batch_id,

        "pipeline": [
            "detect",
            "decide",
            "ai_policy_reconciliation",
            "schedule",
            "execute_one_hour",
            "execute_one_day",
            "customer_response",
            "outcome",
            "metrics",
        ],

        "detection": detection,

        "decisions": decisions,

        "ai_reconciliation": ai_reconciliation,

        "schedule": schedule_now,

        "execution": {
            "one_hour": execution_one_hour,
            "one_day": execution_one_day,
        },

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