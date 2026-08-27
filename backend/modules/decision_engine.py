"""
Decision engine for DunnFlow.

Takes a diagnosed payment (failure_category already set) and decides:
  1. WHAT action to take (retry / send message / auto-retry / manual review)
  2. WHEN to take it (timing rule per category)
  3. WHETHER it's actually allowed to fire right now (guardrails)

This is the single place guardrails are enforced. Nothing in execution.py
should re-check guardrails — if decision_engine says "blocked", execution
must not run. This separation is what makes the system "bounded and
explainable": one place to point to, one place to audit.
"""

from datetime import datetime, timedelta, timezone

from backend.data.db import (
    get_payment,
    count_attempts_last_n_hours,
    log_audit_entry,
)

# ---------- guardrails (hard limits, not suggestions) ----------
MAX_RETRIES = 3
MIN_GAP_HOURS = 24

# ---------- category -> (action_type, delay) rules ----------
# delay is a timedelta from "now" for when the action should be scheduled.
ACTION_RULES = {
    "insufficient_funds": {
        "action_type": "retry_payment",
        "delay": timedelta(days=3),   # payday-aligned retry
        "rationale": "Retrying in 3 days gives the customer's account time to "
                      "refill, e.g. around a salary/payday cycle.",
    },
    "card_expired": {
        "action_type": "send_update_card_message",
        "delay": timedelta(minutes=0),  # send immediately, no point waiting
        "rationale": "Card is expired — no retry will succeed until the "
                      "customer updates it, so we message immediately with "
                      "a payment link instead of retrying blindly.",
    },
    "bank_timeout": {
        "action_type": "auto_retry_same_card",
        "delay": timedelta(hours=1),   # likely transient, retry soon
        "rationale": "Bank/gateway timeouts are usually transient — a quick "
                      "retry on the same card is likely to succeed without "
                      "bothering the customer.",
    },
    "auth_failed": {
        "action_type": "send_update_card_message",
        "delay": timedelta(minutes=0),
        "rationale": "Authentication failures usually need the customer to "
                      "re-attempt with correct OTP — we prompt them directly "
                      "rather than silently retrying on their behalf.",
    },
}


def _guardrail_check(payment_id: str, current_retry_count: int) -> str | None:
    """Returns the name of the guardrail that blocked the action, or None if
    the action is allowed to proceed."""
    if current_retry_count >= MAX_RETRIES:
        return f"max_retries_exceeded (limit={MAX_RETRIES})"

    attempts_in_window = count_attempts_last_n_hours(payment_id, MIN_GAP_HOURS)
    if attempts_in_window > 0:
        return f"min_gap_not_elapsed (limit={MIN_GAP_HOURS}h)"

    return None


def decide(payment: dict) -> dict:
    """
    Decide the next action for a diagnosed payment.

    Returns a dict:
      {
        "payment_id": ...,
        "decision": "scheduled" | "blocked" | "manual_review",
        "action_type": ... or None,
        "scheduled_for": ISO timestamp or None,
        "guardrail_hit": name or None,
        "rationale": human-readable string,
      }
    Also writes an audit_log entry for every decision, including blocked ones —
    a blocked action is just as important to show as an executed one.
    """
    payment_id = payment["payment_id"]
    customer_id = payment["customer_id"]
    category = payment.get("failure_category")
    retry_count = payment.get("retry_count", 0)

    # --- unclassified payments never get automated action ---
    if category is None or category == "unclassified":
        result = {
            "payment_id": payment_id,
            "decision": "manual_review",
            "action_type": None,
            "scheduled_for": None,
            "guardrail_hit": None,
            "rationale": "Failure category is unclassified — routed to manual "
                          "review instead of guessing at an automated action.",
        }
        log_audit_entry({
            "payment_id": payment_id,
            "customer_id": customer_id,
            "stage": "decide",
            "failure_category": category,
            "action_taken": "none",
            "guardrail_hit": None,
            "result": "manual_review",
            "detail": result["rationale"],
        })
        return result

    rule = ACTION_RULES.get(category)
    if rule is None:
        # Defensive fallback: a category exists that has no rule defined.
        # Same treatment as unclassified — never guess.
        result = {
            "payment_id": payment_id,
            "decision": "manual_review",
            "action_type": None,
            "scheduled_for": None,
            "guardrail_hit": None,
            "rationale": f"No action rule defined for category '{category}' — "
                          "routed to manual review.",
        }
        log_audit_entry({
            "payment_id": payment_id,
            "customer_id": customer_id,
            "stage": "decide",
            "failure_category": category,
            "action_taken": "none",
            "guardrail_hit": None,
            "result": "manual_review",
            "detail": result["rationale"],
        })
        return result

    # --- guardrail check happens BEFORE any action is scheduled ---
    guardrail_hit = _guardrail_check(payment_id, retry_count)
    if guardrail_hit:
        result = {
            "payment_id": payment_id,
            "decision": "blocked",
            "action_type": rule["action_type"],
            "scheduled_for": None,
            "guardrail_hit": guardrail_hit,
            "rationale": f"Action '{rule['action_type']}' was blocked by "
                          f"guardrail: {guardrail_hit}.",
        }
        log_audit_entry({
            "payment_id": payment_id,
            "customer_id": customer_id,
            "stage": "guardrail_block",
            "failure_category": category,
            "action_taken": rule["action_type"],
            "guardrail_hit": guardrail_hit,
            "result": "blocked",
            "detail": result["rationale"],
        })
        return result

    # --- allowed: schedule the action ---
    scheduled_for = (datetime.now(timezone.utc) + rule["delay"]).isoformat(timespec="seconds")
    result = {
        "payment_id": payment_id,
        "decision": "scheduled",
        "action_type": rule["action_type"],
        "scheduled_for": scheduled_for,
        "guardrail_hit": None,
        "rationale": rule["rationale"],
    }
    log_audit_entry({
        "payment_id": payment_id,
        "customer_id": customer_id,
        "stage": "decide",
        "failure_category": category,
        "action_taken": rule["action_type"],
        "guardrail_hit": None,
        "result": "scheduled",
        "detail": f"{rule['rationale']} Scheduled for {scheduled_for}.",
    })
    return result


def decide_for_payment_id(payment_id: str) -> dict | None:
    payment = get_payment(payment_id)
    if not payment:
        return None
    return decide(payment)