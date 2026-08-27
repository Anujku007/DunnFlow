"""
Execution module for DunnFlow.

Takes a decision_engine result with decision == "scheduled" and actually
performs the action:
  - retry_payment            -> re-attempt the charge via Razorpay test-mode API
  - auto_retry_same_card     -> same as above, just a different trigger reason
  - send_update_card_message -> simulate sending a message with a payment link

This module NEVER re-checks guardrails — that's decision_engine's job. If a
decision wasn't "scheduled", execution.py refuses to run and logs why. Single
responsibility: given a green light, execute it and record what happened.
"""

from datetime import datetime, timezone

from backend.data.db import (
    get_payment,
    log_retry_attempt,
    get_retry_attempts,
    update_payment_status,
    log_audit_entry,
)
from backend.razorpay_client import retry_payment_test_mode, send_recovery_message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def execute(decision: dict) -> dict:
    """
    Execute a single decision. `decision` is the dict returned by
    decision_engine.decide(). Returns an execution result dict.

    Refuses to run anything that isn't decision == "scheduled" — this is a
    deliberate second line of defense, even though decision_engine should
    never hand us a blocked/manual_review action to execute.
    """
    payment_id = decision["payment_id"]
    payment = get_payment(payment_id)

    if decision["decision"] != "scheduled":
        # Defensive guard — should not normally be reached, but we log loudly
        # if it is, since it would indicate a bug in the orchestrator wiring.
        log_audit_entry({
            "payment_id": payment_id,
            "customer_id": payment["customer_id"] if payment else "unknown",
            "stage": "execute",
            "failure_category": payment.get("failure_category") if payment else None,
            "action_taken": "none",
            "guardrail_hit": "execution_refused_non_scheduled_decision",
            "result": "blocked",
            "detail": f"execute() called with decision status "
                      f"'{decision['decision']}' — refusing to act.",
        })
        return {"payment_id": payment_id, "result": "refused", "detail": "decision not scheduled"}

    action_type = decision["action_type"]
    attempt_number = len(get_retry_attempts(payment_id)) + 1

    if action_type in ("retry_payment", "auto_retry_same_card"):
        api_result = retry_payment_test_mode(payment)
        result = "success" if api_result["status"] == "captured" else "failed"
        result_detail = api_result.get("message", "")
    elif action_type == "send_update_card_message":
        api_result = send_recovery_message(payment)
        # Sending a message "succeeds" if dispatched — actual recovery only
        # happens later if/when the customer updates their card and pays,
        # which for this demo we treat as a separate, later event.
        result = "sent" if api_result["status"] == "sent" else "failed"
        result_detail = api_result.get("message", "")
    else:
        result = "failed"
        result_detail = f"Unknown action_type '{action_type}'"

    log_retry_attempt({
        "payment_id": payment_id,
        "attempt_number": attempt_number,
        "action_type": action_type,
        "scheduled_for": decision["scheduled_for"],
        "executed_at": _now(),
        "result": result,
        "result_detail": result_detail,
    })

    # Update the payment's own retry_count/status based on outcome.
    if result == "success":
        new_status = "recovered"
    elif result == "sent":
        new_status = "pending_retry"   # waiting on customer action
    else:
        new_status = "exhausted" if attempt_number >= 3 else "pending_retry"

    update_payment_status(payment_id, new_status, retry_count=attempt_number)

    log_audit_entry({
        "payment_id": payment_id,
        "customer_id": payment["customer_id"],
        "stage": "execute",
        "failure_category": payment.get("failure_category"),
        "action_taken": action_type,
        "guardrail_hit": None,
        "result": result,
        "detail": f"Attempt #{attempt_number}: {action_type} -> {result}. {result_detail}",
    })

    return {
        "payment_id": payment_id,
        "action_type": action_type,
        "attempt_number": attempt_number,
        "result": result,
        "new_status": new_status,
        "detail": result_detail,
    }