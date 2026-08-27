"""
DunnFlow decision engine.

Responsibility
--------------
Convert a diagnosed invoice into a bounded, explainable recovery decision.

Pipeline:

    detection
        ↓
    diagnosis
        ↓
    decision_engine
        ↓
    scheduler
        ↓
    execution

Important retry-budget rule
---------------------------
The original failed subscription charge is NOT a DunnFlow recovery retry.

Therefore:

    initial failed charge = attempt #1 in payment history
                            but NOT a retry-budget attempt

DunnFlow retry budget:

    recovery attempt #1
    recovery attempt #2
    recovery attempt #3

MAX_AUTOMATED_PAYMENT_RETRIES = 3

The payment_attempts table is the source of truth for this budget.

The subscription.retry_count field is only a persisted summary and is never
used by the decision engine to decide whether another action is allowed.

Action-specific guardrails
---------------------------
Payment retry actions:
    - maximum 3 automated recovery attempts
    - minimum 24-hour gap between recovery attempts

Customer communication:
    - maximum 2 recovery messages
    - minimum 48-hour gap between messages

Manual review:
    - no automated financial action

The decision engine NEVER executes an action.
"""


from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.data.db import (
    create_recovery_action,
    get_batch_run,
    get_invoice,
    get_payment_attempts,
    get_recovery_actions,
    get_subscription,
    log_audit_entry,
)


# ===========================================================================
# HARD GUARDRAILS
# ===========================================================================

MAX_AUTOMATED_PAYMENT_RETRIES = 3
MIN_RETRY_GAP_HOURS = 24

MAX_CUSTOMER_MESSAGES = 2
MIN_MESSAGE_GAP_HOURS = 48


# ===========================================================================
# ACTION TYPES
# ===========================================================================

ACTION_RETRY_PAYMENT = "retry_payment"
ACTION_TRANSIENT_RETRY = "auto_retry_same_card"
ACTION_PAYMENT_METHOD_UPDATE = "payment_method_update"
ACTION_CUSTOMER_ACTION = "customer_action"
ACTION_MANUAL_REVIEW = "manual_review"
ACTION_NONE = "no_action"


PAYMENT_RETRY_ACTIONS = {
    ACTION_RETRY_PAYMENT,
    ACTION_TRANSIENT_RETRY,
}

CUSTOMER_MESSAGE_ACTIONS = {
    ACTION_CUSTOMER_ACTION,
    ACTION_PAYMENT_METHOD_UPDATE,
}


# ===========================================================================
# DECISION POLICIES
# ===========================================================================

ACTION_POLICIES = {
    "insufficient_funds": {
        "action_type": ACTION_RETRY_PAYMENT,
        "delay": timedelta(days=1),
        "priority": "normal",
        "resource_type": "payment_retry",
        "rationale": (
            "Insufficient funds indicates a customer-balance problem. "
            "A delayed retry is preferred to repeated immediate retries."
        ),
    },

    "bank_timeout": {
        "action_type": ACTION_TRANSIENT_RETRY,
        "delay": timedelta(hours=1),
        "priority": "high",
        "resource_type": "payment_retry",
        "rationale": (
            "The bank or gateway timed out, indicating a potentially "
            "transient failure. A retry is preferred before contacting "
            "the customer."
        ),
    },

    "auth_failed": {
        "action_type": ACTION_CUSTOMER_ACTION,
        "delay": timedelta(minutes=0),
        "priority": "normal",
        "resource_type": "customer_message",
        "rationale": (
            "Customer authentication failed. Customer action is required "
            "rather than blindly retrying the payment."
        ),
    },

    "card_expired": {
        "action_type": ACTION_PAYMENT_METHOD_UPDATE,
        "delay": timedelta(minutes=0),
        "priority": "high",
        "resource_type": "customer_message",
        "rationale": (
            "The payment method is expired. DunnFlow requests a payment "
            "method update instead of retrying a known-invalid method."
        ),
    },

    "unclassified": {
        "action_type": ACTION_MANUAL_REVIEW,
        "delay": timedelta(minutes=0),
        "priority": "high",
        "resource_type": "manual",
        "rationale": (
            "The failure signal is not recognized. DunnFlow will not guess "
            "at a financial recovery action and routes the case to manual "
            "review."
        ),
    },
}


# ===========================================================================
# TIME HELPERS
# ===========================================================================

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed.astimezone(
            timezone.utc
        )

    except ValueError:
        return None

def _get_batch_start_time(batch_id: str) -> datetime:
    """
    Return the benchmark's canonical T0.

    All scheduled demo actions are calculated from this timestamp rather
    than from the wall-clock time when the decision engine happens to run.
    """

    batch = get_batch_run(batch_id)

    if not batch:
        raise ValueError(
            f"Batch '{batch_id}' does not exist."
        )

    batch_start = _parse_timestamp(
        batch.get("started_at")
    )

    if batch_start is None:
        raise ValueError(
            f"Batch '{batch_id}' has an invalid started_at timestamp."
        )

    return batch_start


# ===========================================================================
# RETRY / MESSAGE HISTORY
# ===========================================================================

def _automated_retry_count(invoice_id: str) -> int:
    """
    Count ONLY DunnFlow recovery payment attempts.

    The original failed subscription charge is deliberately excluded.

    Example:

        initial_charge
        recovery_payment
        recovery_payment

    returns:

        2
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


def _customer_message_count(invoice_id: str) -> int:
    """
    Count previously created customer-facing recovery actions.
    """

    actions = get_recovery_actions(
        invoice_id=invoice_id
    )

    return sum(
        1
        for action in actions
        if action.get("action_type") in CUSTOMER_MESSAGE_ACTIONS
        and action.get("status") in {
            "planned",
            "executed",
            "awaiting_customer",
        }
    )


def _last_payment_retry_time(
    invoice_id: str,
) -> datetime | None:
    """
    Return the timestamp of the most recent DunnFlow recovery attempt.

    The original initial_charge is ignored.
    """

    attempts = get_payment_attempts(
        invoice_id=invoice_id
    )

    timestamps: list[datetime] = []

    for attempt in attempts:

        if attempt.get("attempt_type") not in {
            "auto_retry",
            "manual_retry",
            "recovery_payment",
        }:
            continue

        timestamp = _parse_timestamp(
            attempt.get("executed_at")
            or attempt.get("created_at")
        )

        if timestamp:
            timestamps.append(timestamp)

    return max(timestamps) if timestamps else None


def _last_message_time(
    invoice_id: str,
) -> datetime | None:
    """
    Return the timestamp of the most recent customer-facing recovery action.
    """

    actions = get_recovery_actions(
        invoice_id=invoice_id
    )

    timestamps: list[datetime] = []

    for action in actions:

        if action.get("action_type") not in CUSTOMER_MESSAGE_ACTIONS:
            continue

        timestamp = _parse_timestamp(
            action.get("executed_at")
            or action.get("created_at")
        )

        if timestamp:
            timestamps.append(timestamp)

    return max(timestamps) if timestamps else None


# ===========================================================================
# GUARDRAILS
# ===========================================================================

def _check_payment_retry_guardrails(
    invoice_id: str,
) -> str | None:
    """
    Check guardrails that apply ONLY to payment retry actions.

    This function uses payment_attempt history rather than the subscription's
    retry_count field.

    Returns:
        guardrail name if blocked
        None if allowed
    """

    retry_count = _automated_retry_count(
        invoice_id
    )

    # The original failed charge does not count.
    if retry_count >= MAX_AUTOMATED_PAYMENT_RETRIES:
        return (
            "max_automated_payment_retries_exceeded"
            f"(limit={MAX_AUTOMATED_PAYMENT_RETRIES})"
        )

    last_retry = _last_payment_retry_time(
        invoice_id
    )

    if last_retry:

        elapsed = _now() - last_retry

        minimum_gap = timedelta(
            hours=MIN_RETRY_GAP_HOURS
        )

        if elapsed < minimum_gap:

            remaining = minimum_gap - elapsed

            remaining_hours = max(
                1,
                int(
                    remaining.total_seconds()
                    // 3600
                ),
            )

            return (
                "minimum_retry_gap_not_elapsed"
                f"(limit={MIN_RETRY_GAP_HOURS}h,"
                f"remaining≈{remaining_hours}h)"
            )

    return None


def _check_message_guardrails(
    invoice_id: str,
) -> str | None:
    """
    Check guardrails that apply ONLY to customer communications.
    """

    message_count = _customer_message_count(
        invoice_id
    )

    if message_count >= MAX_CUSTOMER_MESSAGES:
        return (
            "max_customer_recovery_messages_exceeded"
            f"(limit={MAX_CUSTOMER_MESSAGES})"
        )

    last_message = _last_message_time(
        invoice_id
    )

    if last_message:

        elapsed = _now() - last_message

        minimum_gap = timedelta(
            hours=MIN_MESSAGE_GAP_HOURS
        )

        if elapsed < minimum_gap:

            remaining = minimum_gap - elapsed

            remaining_hours = max(
                1,
                int(
                    remaining.total_seconds()
                    // 3600
                ),
            )

            return (
                "minimum_message_gap_not_elapsed"
                f"(limit={MIN_MESSAGE_GAP_HOURS}h,"
                f"remaining≈{remaining_hours}h)"
            )

    return None


def _check_guardrails(
    invoice_id: str,
    resource_type: str,
) -> str | None:

    if resource_type == "payment_retry":
        return _check_payment_retry_guardrails(
            invoice_id
        )

    if resource_type == "customer_message":
        return _check_message_guardrails(
            invoice_id
        )

    # Manual review / non-automated action.
    return None


# ===========================================================================
# DECISION
# ===========================================================================

def decide_for_invoice(
    invoice_id: str,
    *,
    persist: bool = True,
) -> dict:
    """
    Generate a bounded recovery decision for one invoice.
    """

    invoice = get_invoice(
        invoice_id
    )

    if not invoice:

        return {
            "invoice_id": invoice_id,
            "subscription_id": None,
            "batch_id": None,
            "decision": "invalid",
            "action_type": ACTION_NONE,
            "scheduled_for": None,
            "priority": "high",
            "guardrail_hit": "invoice_not_found",
            "rationale": "Invoice does not exist.",
        }

    subscription = get_subscription(
        invoice["subscription_id"]
    )

    # ---------------------------------------------------------------
    # Missing subscription
    # ---------------------------------------------------------------

    if not subscription:

        result = {
            "invoice_id": invoice_id,
            "subscription_id": invoice[
                "subscription_id"
            ],
            "batch_id": invoice["batch_id"],
            "decision": "manual_review",
            "action_type": ACTION_MANUAL_REVIEW,
            "scheduled_for": None,
            "priority": "high",
            "guardrail_hit": "subscription_not_found",
            "rationale": (
                "Invoice references a missing subscription. "
                "Automated recovery is unsafe."
            ),
        }

        if persist:
            _persist_decision(
                invoice,
                result,
            )

        return result

    # ---------------------------------------------------------------
    # Paid / terminal invoice
    # ---------------------------------------------------------------

    if invoice["status"] in {
        "paid",
        "cancelled",
        "expired",
    }:

        result = {
            "invoice_id": invoice_id,
            "subscription_id": subscription[
                "subscription_id"
            ],
            "batch_id": invoice["batch_id"],
            "decision": "no_action",
            "action_type": ACTION_NONE,
            "scheduled_for": None,
            "priority": "normal",
            "guardrail_hit": "invoice_not_recoverable",
            "rationale": (
                f"Invoice status is '{invoice['status']}'. "
                "No recovery action is permitted."
            ),
        }

        if persist:
            _persist_decision(
                invoice,
                result,
            )

        return result

    # ---------------------------------------------------------------
    # Determine policy from persisted diagnosis
    # ---------------------------------------------------------------

    category = (
        invoice.get("failure_category")
        or "unclassified"
    )

    policy = ACTION_POLICIES.get(
        category,
        ACTION_POLICIES["unclassified"],
    )

    action_type = policy[
        "action_type"
    ]

    # ---------------------------------------------------------------
    # Unknown failure → manual review
    # ---------------------------------------------------------------

    if action_type == ACTION_MANUAL_REVIEW:

        result = {
            "invoice_id": invoice_id,
            "subscription_id": subscription[
                "subscription_id"
            ],
            "batch_id": invoice["batch_id"],
            "decision": "manual_review",
            "action_type": ACTION_MANUAL_REVIEW,
            "scheduled_for": None,
            "priority": policy["priority"],
            "guardrail_hit": None,
            "rationale": policy["rationale"],
        }

        if persist:
            _persist_decision(
                invoice,
                result,
            )

        return result

    # ---------------------------------------------------------------
    # Apply the correct action-specific guardrail
    # ---------------------------------------------------------------

    guardrail_hit = _check_guardrails(
        invoice_id,
        policy["resource_type"],
    )

    if guardrail_hit:

        result = {
            "invoice_id": invoice_id,
            "subscription_id": subscription[
                "subscription_id"
            ],
            "batch_id": invoice["batch_id"],
            "decision": "blocked",
            "action_type": action_type,
            "scheduled_for": None,
            "priority": policy["priority"],
            "guardrail_hit": guardrail_hit,
            "rationale": (
                f"Action '{action_type}' was blocked by "
                f"guardrail '{guardrail_hit}'. "
                "DunnFlow will not continue automated recovery."
            ),
        }

        if persist:
            _persist_decision(
                invoice,
                result,
            )

        return result

    # ---------------------------------------------------------------
    # Schedule allowed action
    # ---------------------------------------------------------------

    batch_start = _get_batch_start_time(
    invoice["batch_id"]
)

    scheduled_time = (
    batch_start
    + policy["delay"]
)

    scheduled_for = scheduled_time.isoformat(
    timespec="seconds"
)

    result = {
        "invoice_id": invoice_id,
        "subscription_id": subscription[
            "subscription_id"
        ],
        "batch_id": invoice["batch_id"],
        "decision": "scheduled",
        "action_type": action_type,
        "scheduled_for": scheduled_for,
        "priority": policy["priority"],
        "guardrail_hit": None,
        "rationale": policy["rationale"],
    }

    if persist:
        _persist_decision(
            invoice,
            result,
        )

    return result


# ===========================================================================
# PERSIST DECISION
# ===========================================================================

def _persist_decision(
    invoice: dict,
    decision: dict,
) -> int:
    """
    Persist a decision as a recovery action and audit event.
    """

    if decision["decision"] == "blocked":
        action_status = "blocked"

    elif decision["decision"] == "manual_review":
        action_status = "planned"

    elif decision["decision"] == "no_action":
        action_status = "cancelled"

    else:
        action_status = "planned"

    action_id = create_recovery_action(
        {
            "batch_id": invoice["batch_id"],
            "subscription_id": invoice[
                "subscription_id"
            ],
            "invoice_id": invoice[
                "invoice_id"
            ],
            "action_type": decision[
                "action_type"
            ],
            "reason": decision[
                "rationale"
            ],
            "priority": decision[
                "priority"
            ],
            "scheduled_for": decision[
                "scheduled_for"
            ],
            "executed_at": None,
            "status": action_status,
            "guardrail_hit": decision[
                "guardrail_hit"
            ],
        }
    )

    audit_stage = "decide"

    if decision["decision"] == "blocked":
        audit_stage = "guardrail_block"

    log_audit_entry(
        {
            "batch_id": invoice["batch_id"],
            "subscription_id": invoice[
                "subscription_id"
            ],
            "invoice_id": invoice[
                "invoice_id"
            ],
            "payment_attempt_id": None,
            "stage": audit_stage,
            "failure_category": invoice.get(
                "failure_category"
            ),
            "action_taken": decision[
                "action_type"
            ],
            "guardrail_hit": decision[
                "guardrail_hit"
            ],
            "result": decision[
                "decision"
            ],
            "detail": (
                f"Decision: "
                f"{decision['action_type']}. "
                f"Reason: "
                f"{decision['rationale']} "
                f"Scheduled for: "
                f"{decision['scheduled_for'] or 'not scheduled'}."
            ),
        }
    )

    return action_id


# ===========================================================================
# BATCH DECISION
# ===========================================================================

def decide_batch(
    batch_id: str,
) -> dict:
    """
    Generate decisions for every unpaid invoice in a batch.

    No action is executed here.
    """

    from backend.data.db import get_invoices

    invoices = get_invoices(
        batch_id=batch_id
    )

    decisions: list[dict] = []

    decision_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}

    for invoice in invoices:

        if invoice["status"] != "issued":
            continue

        decision = decide_for_invoice(
            invoice["invoice_id"]
        )

        decisions.append(
            decision
        )

        decision_type = decision[
            "decision"
        ]

        action_type = decision[
            "action_type"
        ]

        decision_counts[
            decision_type
        ] = (
            decision_counts.get(
                decision_type,
                0,
            )
            + 1
        )

        action_counts[
            action_type
        ] = (
            action_counts.get(
                action_type,
                0,
            )
            + 1
        )

    return {
        "batch_id": batch_id,
        "decided_count": len(decisions),
        "decision_counts": decision_counts,
        "action_counts": action_counts,
        "decisions": decisions,
    }


# ===========================================================================
# CLI
# ===========================================================================

if __name__ == "__main__":

    from backend.data.db import list_batch_runs

    batches = list_batch_runs(
        limit=1
    )

    if not batches:
        print("No batch runs found.")
        raise SystemExit(1)

    batch_id = batches[0]["batch_id"]

    report = decide_batch(
        batch_id
    )

    print()
    print("=" * 64)
    print("DUNNFLOW DECISION ENGINE")
    print("=" * 64)

    print(
        f"Batch ID:             "
        f"{batch_id}"
    )

    print(
        f"Decisions generated:  "
        f"{report['decided_count']}"
    )

    print()
    print("Decision distribution:")

    for decision, count in report[
        "decision_counts"
    ].items():

        print(
            f"  {decision:<22} "
            f"{count}"
        )

    print()
    print("Action distribution:")

    for action, count in report[
        "action_counts"
    ].items():

        print(
            f"  {action:<30} "
            f"{count}"
        )

    print("=" * 64)