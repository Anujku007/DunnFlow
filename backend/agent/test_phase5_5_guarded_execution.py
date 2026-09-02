from datetime import datetime, timedelta, timezone

from backend.data.db import (
    clear_all_data,
    init_db,
    create_batch_run,
    upsert_subscription,
    upsert_invoice,
    create_payment_attempt,
    create_recovery_action,
    get_recovery_actions,
)
from backend.agent.recovery_agent import RecoveryAgent


BATCH_ID = "phase5_5_guarded_execution_test"
INVOICE_ID = "inv_phase5_5"
SUBSCRIPTION_ID = "sub_phase5_5"


def setup():
    init_db()
    clear_all_data()

    now = datetime.now(timezone.utc).isoformat()

    create_batch_run(
        BATCH_ID,
        started_at=now,
        status="running",
    )

    upsert_subscription(
        {
            "subscription_id": SUBSCRIPTION_ID,
            "batch_id": BATCH_ID,
            "customer_id": "cust_phase5_5",
            "amount": 10000,
            "currency": "INR",
            "status": "pending",
            "current_cycle": 1,
            "retry_count": 0,
            "created_at": now,
            "updated_at": now,
        }
    )

    upsert_invoice(
        {
            "invoice_id": INVOICE_ID,
            "batch_id": BATCH_ID,
            "subscription_id": SUBSCRIPTION_ID,
            "amount": 10000,
            "currency": "INR",
            "status": "issued",
            "issued_at": now,
            "failure_category": "bank_timeout",
            "created_at": now,
            "updated_at": now,
        }
    )

    create_payment_attempt(
        {
            "batch_id": BATCH_ID,
            "invoice_id": INVOICE_ID,
            "subscription_id": SUBSCRIPTION_ID,
            "attempt_number": 1,
            "attempt_type": "initial",
            "action_type": None,
            "scheduled_for": None,
            "executed_at": now,
            "result": "failed",
            "raw_error_code": "payment_timed_out",
            "failure_reason": "Bank timeout",
            "gateway_status": "failed",
            "result_detail": "Phase 5.5 test failure",
            "created_at": now,
        }
    )


def main():
    setup()

    now = datetime.now(timezone.utc)

    create_recovery_action(
        {
            "batch_id": BATCH_ID,
            "subscription_id": SUBSCRIPTION_ID,
            "invoice_id": INVOICE_ID,
            "action_type": "auto_retry_same_card",
            "reason": "Phase 5.5 guarded execution test",
            "priority": "high",
            "scheduled_for": now.isoformat(),
            "executed_at": None,
            "status": "planned",
            "guardrail_hit": None,
            "created_at": now.isoformat(),
        }
    )

    create_recovery_action(
        {
            "batch_id": BATCH_ID,
            "subscription_id": SUBSCRIPTION_ID,
            "invoice_id": INVOICE_ID,
            "action_type": "auto_retry_same_card",
            "reason": "Future action must not execute",
            "priority": "high",
            "scheduled_for": (
                now + timedelta(days=1)
            ).isoformat(),
            "executed_at": None,
            "status": "planned",
            "guardrail_hit": None,
            "created_at": now.isoformat(),
        }
    )

    agent = RecoveryAgent(BATCH_ID)

    result = agent.execute(as_of=now)

    print("AGENT STATE:", agent.context.state.value)
    print("STATE HISTORY:", agent.context.history)

    execution = agent.context.result["executions"][-1]

    print(
        "DUE ACTIONS FOUND:",
        execution["due_actions_found"],
    )

    print(
        "ACTIONS EXECUTED:",
        execution["actions_executed"],
    )

    actions = get_recovery_actions(
        batch_id=BATCH_ID
    )

    executed = [
        action
        for action in actions
        if action.get("status") == "executed"
    ]

    planned = [
        action
        for action in actions
        if action.get("status") == "planned"
    ]

    print("EXECUTED ACTIONS:", len(executed))
    print("PLANNED ACTIONS REMAINING:", len(planned))

    assert execution["due_actions_found"] == 1
    assert execution["actions_executed"] == 1
    assert len(executed) == 1
    assert len(planned) == 1

    print("DUE-ONLY EXECUTION: PASS")
    print("FUTURE ACTION PROTECTED: PASS")
    print("EXISTING EXECUTION ENGINE DELEGATED: PASS")
    print("PHASE 5.5 GUARDED EXECUTION TEST: PASS")


if __name__ == "__main__":
    main()

