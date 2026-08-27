"""
DunnFlow customer-response simulator.

Purpose
-------
Simulate what happens AFTER DunnFlow has sent a customer-facing recovery
action.

This module covers:

    customer_action
    payment_method_update

It deliberately does NOT treat message delivery as revenue recovery.

Instead:

    recovery action
        ↓
    customer responds
        ↓
    payment attempt
        ↓
    success / failure
        ↓
    verified revenue event

Synthetic benchmark behavior
-----------------------------
The benchmark is deterministic.

For the current 24 customer-facing cases:

    auth_failed:
        6 recover
        6 remain in progress

    card_expired:
        8 recover
        4 remain in progress

Therefore:

    14 additional recoveries
    10 remain in progress

Combined with the 15 retry-driven recoveries already produced:

    29 recovered
    10 in progress from customer-action cases
    plus the remaining insufficient-funds states
    plus exhausted / blocked / manual-review cases

Important
---------
This is a SYNTHETIC customer-response simulator.

It does not claim to send real SMS, WhatsApp, email, or Razorpay Checkout
messages.

A later production/Test Mode adapter can replace the simulation while
preserving the same database and outcome interfaces.
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.data.db import (
    create_payment_attempt,
    get_batch_metrics,
    get_invoice,
    get_payment_attempts,
    get_recovery_actions,
    get_subscription,
    log_audit_entry,
    record_revenue_event,
    update_batch_run,
    update_invoice_status,
    update_recovery_action,
    update_subscription_status,
)


# ============================================================================
# CONFIGURATION
# ============================================================================

EXECUTION_MODE = "synthetic_customer_response"

CUSTOMER_ACTIONS = {
    "customer_action",
    "payment_method_update",
}


# ============================================================================
# TIME
# ============================================================================

def _now() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )


# ============================================================================
# CUSTOMER RESPONSE POLICY
# ============================================================================

def _customer_will_respond(
    invoice: dict,
) -> bool:
    """
    Deterministically decide whether the benchmark customer responds.

    Rules:

        auth_failed:
            even-numbered subscription IDs respond

        card_expired:
            first 8 benchmark cases respond

    This is deliberately deterministic rather than probabilistic so the
    benchmark remains reproducible.
    """

    category = invoice.get(
        "failure_category"
    )

    subscription_number = _subscription_number(
        invoice["subscription_id"]
    )

    if category == "auth_failed":
        return subscription_number % 2 == 0

    if category == "card_expired":
        return 43 <= subscription_number <= 50

    return False


def _subscription_number(
    subscription_id: str,
) -> int:
    """
    Extract the numeric suffix from IDs such as:

        sub_dunnflow_031
    """

    try:
        return int(
            subscription_id.rsplit(
                "_",
                1,
            )[-1]
        )
    except (ValueError, AttributeError):
        return 0


# ============================================================================
# RESPONSE HISTORY
# ============================================================================

def _already_processed(
    invoice_id: str,
) -> bool:
    """
    Prevent a customer response from being simulated twice for the same
    invoice.
    """

    actions = get_recovery_actions(
        invoice_id=invoice_id
    )

    return any(
        action.get("status") in {
            "customer_responded",
            "customer_no_response",
        }
        for action in actions
    )


# ============================================================================
# SUCCESSFUL CUSTOMER RECOVERY
# ============================================================================

def _record_customer_recovery(
    *,
    invoice: dict,
    subscription: dict,
    action: dict,
    executed_at: str,
) -> dict:
    """
    Create a successful customer-driven payment attempt and record the
    complete financial recovery chain.
    """

    existing_attempts = get_payment_attempts(
        invoice_id=invoice["invoice_id"]
    )

    if existing_attempts:
        payment_attempt_number = (
            max(
                int(
                    attempt["attempt_number"]
                )
                for attempt in existing_attempts
            )
            + 1
        )
    else:
        payment_attempt_number = 1

    payment_id = (
        f"pay_customer_dunnflow_"
        f"{invoice['invoice_id']}_"
        f"{payment_attempt_number:02d}"
    )

    attempt_id = create_payment_attempt(
        {
            "batch_id": invoice["batch_id"],
            "invoice_id": invoice["invoice_id"],
            "subscription_id": subscription[
                "subscription_id"
            ],
            "razorpay_payment_id": payment_id,
            "attempt_number": payment_attempt_number,
            "attempt_type": "customer_payment",
            "action_type": action[
                "action_type"
            ],
            "scheduled_for": action.get(
                "scheduled_for"
            ),
            "executed_at": executed_at,
            "result": "success",
            "raw_error_code": None,
            "failure_reason": None,
            "gateway_status": "captured",
            "result_detail": (
                "Synthetic customer response resulted in a successful "
                "payment."
            ),
            "created_at": executed_at,
        }
    )

    amount = int(
        invoice["amount"]
    )

    # ------------------------------------------------------------------
    # Invoice paid
    # ------------------------------------------------------------------

    update_invoice_status(
        invoice["invoice_id"],
        "paid",
        paid_at=executed_at,
    )

    # ------------------------------------------------------------------
    # Subscription active
    # ------------------------------------------------------------------

    update_subscription_status(
        subscription["subscription_id"],
        "active",
    )

    # ------------------------------------------------------------------
    # Payment captured
    # ------------------------------------------------------------------

    record_revenue_event(
        {
            "batch_id": invoice["batch_id"],
            "subscription_id": subscription[
                "subscription_id"
            ],
            "invoice_id": invoice[
                "invoice_id"
            ],
            "payment_attempt_id": attempt_id,
            "event_type": "payment_captured",
            "amount": amount,
            "event_timestamp": executed_at,
            "detail": (
                f"Customer completed the recovery flow and payment "
                f"{payment_id} was captured."
            ),
        }
    )

    # ------------------------------------------------------------------
    # Invoice paid
    # ------------------------------------------------------------------

    record_revenue_event(
        {
            "batch_id": invoice["batch_id"],
            "subscription_id": subscription[
                "subscription_id"
            ],
            "invoice_id": invoice[
                "invoice_id"
            ],
            "payment_attempt_id": attempt_id,
            "event_type": "invoice_paid",
            "amount": amount,
            "event_timestamp": executed_at,
            "detail": (
                f"Invoice {invoice['invoice_id']} was paid after "
                "customer recovery."
            ),
        }
    )

    # ------------------------------------------------------------------
    # Authoritative recovery confirmation
    # ------------------------------------------------------------------

    record_revenue_event(
        {
            "batch_id": invoice["batch_id"],
            "subscription_id": subscription[
                "subscription_id"
            ],
            "invoice_id": invoice[
                "invoice_id"
            ],
            "payment_attempt_id": attempt_id,
            "event_type": "recovery_confirmed",
            "amount": amount,
            "event_timestamp": executed_at,
            "detail": (
                f"₹{amount / 100:,.2f} recovered through "
                "customer-driven payment recovery."
            ),
        }
    )

    update_recovery_action(
        action["action_id"],
        status="customer_responded",
        executed_at=executed_at,
    )

    log_audit_entry(
        {
            "batch_id": invoice["batch_id"],
            "subscription_id": subscription[
                "subscription_id"
            ],
            "invoice_id": invoice[
                "invoice_id"
            ],
            "payment_attempt_id": attempt_id,
            "stage": "execute",
            "failure_category": invoice.get(
                "failure_category"
            ),
            "action_taken": action[
                "action_type"
            ],
            "guardrail_hit": None,
            "result": "success",
            "detail": (
                f"Customer responded to recovery action "
                f"'{action['action_type']}'. "
                f"Payment attempt #{payment_attempt_number} "
                f"succeeded and ₹{amount / 100:,.2f} was recovered. "
                f"Execution mode: {EXECUTION_MODE}."
            ),
        }
    )

    return {
        "action_id": action["action_id"],
        "invoice_id": invoice["invoice_id"],
        "action_type": action["action_type"],
        "payment_attempt_id": attempt_id,
        "payment_id": payment_id,
        "payment_attempt_number": payment_attempt_number,
        "customer_responded": True,
        "result": "success",
        "status": "recovered",
        "recovered": True,
        "amount_recovered": amount,
        "detail": (
            "Customer completed the recovery flow successfully."
        ),
    }


# ============================================================================
# NO RESPONSE
# ============================================================================

def _record_no_customer_response(
    *,
    invoice: dict,
    subscription: dict,
    action: dict,
) -> dict:
    """
    Record that the customer did not respond.

    No payment attempt and NO recovery event are created.
    """

    executed_at = _now()

    update_recovery_action(
        action["action_id"],
        status="customer_no_response",
        executed_at=executed_at,
    )

    log_audit_entry(
        {
            "batch_id": invoice["batch_id"],
            "subscription_id": subscription[
                "subscription_id"
            ],
            "invoice_id": invoice[
                "invoice_id"
            ],
            "payment_attempt_id": None,
            "stage": "outcome",
            "failure_category": invoice.get(
                "failure_category"
            ),
            "action_taken": action[
                "action_type"
            ],
            "guardrail_hit": None,
            "result": "in_progress",
            "detail": (
                "Customer did not respond to the recovery action. "
                "No payment was attempted and no revenue was counted "
                "as recovered."
            ),
        }
    )

    return {
        "action_id": action["action_id"],
        "invoice_id": invoice["invoice_id"],
        "action_type": action["action_type"],
        "customer_responded": False,
        "result": "no_response",
        "status": "in_progress",
        "recovered": False,
        "amount_recovered": 0,
        "detail": (
            "Customer did not respond; recovery remains in progress."
        ),
    }


# ============================================================================
# PROCESS ONE CUSTOMER ACTION
# ============================================================================

def process_customer_action(
    action_id: int,
) -> dict:
    """
    Process one customer-facing recovery action.
    """

    from backend.data.db import get_recovery_action

    action = get_recovery_action(
        action_id
    )

    if not action:
        return {
            "action_id": action_id,
            "status": "invalid",
            "result": "failed",
            "recovered": False,
            "amount_recovered": 0,
            "detail": (
                "Recovery action does not exist."
            ),
        }

    if action["action_type"] not in CUSTOMER_ACTIONS:
        return {
            "action_id": action_id,
            "status": "not_applicable",
            "result": "skipped",
            "recovered": False,
            "amount_recovered": 0,
            "detail": (
                f"Action '{action['action_type']}' is not a "
                "customer-response action."
            ),
        }

    if action["status"] != "awaiting_customer":
        return {
            "action_id": action_id,
            "status": action["status"],
            "result": "skipped",
            "recovered": False,
            "amount_recovered": 0,
            "detail": (
                f"Customer response cannot be processed because "
                f"action status is '{action['status']}'."
            ),
        }

    invoice = get_invoice(
        action["invoice_id"]
    )

    subscription = get_subscription(
        action["subscription_id"]
    )

    if not invoice or not subscription:

        update_recovery_action(
            action_id,
            status="blocked",
            executed_at=_now(),
            guardrail_hit="recovery_context_missing",
        )

        return {
            "action_id": action_id,
            "status": "blocked",
            "result": "failed",
            "recovered": False,
            "amount_recovered": 0,
            "detail": (
                "Invoice or subscription context is missing."
            ),
        }

    # Do not respond to something already paid.
    if invoice["status"] == "paid":

        update_recovery_action(
            action_id,
            status="customer_responded",
            executed_at=_now(),
        )

        return {
            "action_id": action_id,
            "status": "already_recovered",
            "result": "skipped",
            "recovered": False,
            "amount_recovered": 0,
            "detail": (
                "Invoice was already recovered before customer "
                "response processing."
            ),
        }

    if _already_processed(
        invoice["invoice_id"]
    ):
        return {
            "action_id": action_id,
            "status": "already_processed",
            "result": "skipped",
            "recovered": False,
            "amount_recovered": 0,
            "detail": (
                "Customer response for this invoice has already "
                "been processed."
            ),
        }

    # Deterministic benchmark customer behavior.
    if _customer_will_respond(
        invoice
    ):
        return _record_customer_recovery(
            invoice=invoice,
            subscription=subscription,
            action=action,
            executed_at=_now(),
        )

    return _record_no_customer_response(
        invoice=invoice,
        subscription=subscription,
        action=action,
    )


# ============================================================================
# REFRESH BATCH METRICS
# ============================================================================

def refresh_customer_recovery_metrics(
    batch_id: str,
) -> dict:
    """
    Refresh the standard batch metrics after customer responses.
    """

    from backend.data.db import get_batch_metrics

    metrics = get_batch_metrics(
        batch_id
    )

    # The metrics are already calculated from source-of-truth tables.
    # This wrapper exists to make the customer-response boundary explicit.
    return metrics


# ============================================================================
# BATCH CUSTOMER RESPONSE
# ============================================================================

def process_customer_responses(
    batch_id: str,
) -> dict:
    """
    Process all customer-facing recovery actions that are currently
    awaiting_customer.

    No messages are sent here.

    This simulates the subsequent customer response event.
    """

    actions = get_recovery_actions(
        batch_id=batch_id,
        status="awaiting_customer",
    )

    results = []

    for action in actions:

        result = process_customer_action(
            action["action_id"]
        )

        results.append(
            result
        )

    metrics = refresh_customer_recovery_metrics(
        batch_id
    )

    recovered_amount = sum(
        int(result.get("amount_recovered", 0))
        for result in results
    )

    recovered_count = sum(
        1
        for result in results
        if result.get("recovered")
    )

    no_response_count = sum(
        1
        for result in results
        if result.get("result") == "no_response"
    )

    return {
        "batch_id": batch_id,
        "execution_mode": EXECUTION_MODE,
        "actions_processed": len(results),
        "customer_recoveries": recovered_count,
        "customer_no_response": no_response_count,
        "amount_recovered": recovered_amount,
        "results": results,
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

    batch_id = batches[0]["batch_id"]

    report = process_customer_responses(
        batch_id
    )

    print()
    print("=" * 68)
    print("DUNNFLOW CUSTOMER RESPONSE")
    print("=" * 68)

    print(
        f"Batch ID:             "
        f"{report['batch_id']}"
    )

    print(
        f"Execution mode:       "
        f"{report['execution_mode']}"
    )

    print(
        f"Actions processed:    "
        f"{report['actions_processed']}"
    )

    print(
        f"Customers recovered:  "
        f"{report['customer_recoveries']}"
    )

    print(
        f"No response:          "
        f"{report['customer_no_response']}"
    )

    print(
        f"Amount recovered:     "
        f"₹{report['amount_recovered'] / 100:,.2f}"
    )

    print()
    print(
        f"Batch total recovered: "
        f"₹{report['metrics']['amount_recovered'] / 100:,.2f}"
    )

    print(
        f"Overall recovery rate: "
        f"{report['metrics']['recovery_rate_pct']}%"
    )

    print("=" * 68)