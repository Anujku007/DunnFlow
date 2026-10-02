"""
DunnFlow execution engine.

Pipeline:

    detection
        ↓
    diagnosis
        ↓
    decision
        ↓
    scheduler / due-action gate
        ↓
    execution
        ↓
    verified recovery
        ↓
    metrics

Important rules:
- Only planned actions can be executed.
- Future actions must pass through scheduler.py first.
- The original failed subscription charge does NOT count against the
  DunnFlow automated recovery retry budget.
- A customer message is NOT revenue recovery.
- Only a successful payment attempt creates recovery_confirmed revenue.
- The current benchmark uses deterministic synthetic execution.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone


# ============================================================================
# DATABASE
# ============================================================================

from backend.integrations.razorpay_client import RazorpayAPIError, RazorpayClient

from backend.data.db import (
    attach_razorpay_order_to_invoice,
    create_payment_attempt,
    get_batch_metrics,
    get_batch_run,
    get_invoice,
    get_invoices,
    get_payment_attempts,
    get_recovery_action,
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

EXECUTION_MODE = os.getenv(
    "DUNNFLOW_EXECUTION_MODE",
    "synthetic_test_mode",
)

MAX_AUTOMATED_PAYMENT_RETRIES = 3

PAYMENT_RETRY_ACTIONS = {
    "retry_payment",
    "auto_retry_same_card",
}

CUSTOMER_ACTIONS = {
    "customer_action",
    "payment_method_update",
}

NON_EXECUTABLE_ACTIONS = {
    "manual_review",
    "no_action",
}


# ============================================================================
# TIME
# ============================================================================

def _now() -> str:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )


# ============================================================================
# ATTEMPT NUMBERING
# ============================================================================

def _next_payment_attempt_number(invoice_id: str) -> int:
    """
    Return the next payment-history attempt number.

    Example:

        #1 = initial subscription charge
        #2 = recovery attempt #1
        #3 = recovery attempt #2
        #4 = recovery attempt #3
    """

    attempts = get_payment_attempts(
        invoice_id=invoice_id
    )

    if not attempts:
        return 1

    return (
        max(
            int(attempt["attempt_number"])
            for attempt in attempts
        )
        + 1
    )


def _automated_retry_count(invoice_id: str) -> int:
    """
    Count only DunnFlow automated recovery attempts.

    The original initial subscription charge is excluded.
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


# ============================================================================
# SYNTHETIC PAYMENT GATEWAY
# ============================================================================

def _simulate_payment_attempt(
    invoice: dict,
    subscription: dict,
    recovery_attempt_number: int,
) -> dict:
    """
    Deterministic synthetic payment behavior for the benchmark.

    This is intentionally NOT presented as a real Razorpay API response.

    Benchmark behavior:

    bank_timeout:
        recovery attempt #1 -> success

    insufficient_funds:
        recovery attempt #1 -> failure
        recovery attempt #2 -> success
        recovery attempt #3 -> failure
    """

    category = invoice.get(
        "failure_category"
    )

    # ------------------------------------------------------------------
    # BANK TIMEOUT
    # ------------------------------------------------------------------

    if category == "bank_timeout":

        if recovery_attempt_number == 1:
            return {
                "status": "captured",
                "gateway_status": "captured",
                "raw_error_code": None,
                "failure_reason": None,
                "message": (
                    "Synthetic test gateway: transient bank timeout "
                    "cleared on recovery attempt #1."
                ),
            }

        return {
            "status": "failed",
            "gateway_status": "failed",
            "raw_error_code": "payment_timed_out",
            "failure_reason": (
                "Synthetic test gateway: bank timeout persisted."
            ),
            "message": (
                f"Synthetic test gateway: bank-timeout recovery "
                f"attempt #{recovery_attempt_number} failed."
            ),
        }

    # ------------------------------------------------------------------
    # INSUFFICIENT FUNDS
    # ------------------------------------------------------------------

    if category == "insufficient_funds":

        if recovery_attempt_number == 1:
            return {
                "status": "failed",
                "gateway_status": "failed",
                "raw_error_code": "insufficient_fund",
                "failure_reason": (
                    "Synthetic test gateway: insufficient balance "
                    "is still present."
                ),
                "message": (
                    "Synthetic test gateway: recovery attempt #1 failed."
                ),
            }

        if recovery_attempt_number == 2:
            return {
                "status": "captured",
                "gateway_status": "captured",
                "raw_error_code": None,
                "failure_reason": None,
                "message": (
                    "Synthetic test gateway: payment succeeded "
                    "on recovery attempt #2."
                ),
            }

        if recovery_attempt_number == 3:
            return {
                "status": "failed",
                "gateway_status": "failed",
                "raw_error_code": "insufficient_fund",
                "failure_reason": (
                    "Synthetic test gateway: insufficient balance "
                    "persisted through the final allowed retry."
                ),
                "message": (
                    "Synthetic test gateway: recovery attempt #3 failed."
                ),
            }

    # ------------------------------------------------------------------
    # UNSUPPORTED AUTOMATIC PAYMENT
    # ------------------------------------------------------------------

    return {
        "status": "failed",
        "gateway_status": "failed",
        "raw_error_code": "unsupported_automatic_recovery",
        "failure_reason": (
            f"Automatic payment recovery is not supported for "
            f"category '{category}'."
        ),
        "message": (
            f"No automatic payment execution rule exists for "
            f"category '{category}'."
        ),
    }


# ============================================================================
# SUCCESSFUL RECOVERY
# ============================================================================

def _record_successful_recovery(
    invoice: dict,
    subscription: dict,
    attempt_id: int,
    payment_id: str,
    executed_at: str,
) -> None:
    """
    Record a verified successful recovery.

    Financial chain:

        payment captured
            ↓
        invoice paid
            ↓
        subscription active
            ↓
        recovery_confirmed
    """

    amount = int(
        invoice["amount"]
    )

    # ------------------------------------------------------------------
    # Invoice becomes paid
    # ------------------------------------------------------------------

    update_invoice_status(
        invoice["invoice_id"],
        "paid",
        paid_at=executed_at,
    )

    # ------------------------------------------------------------------
    # Subscription becomes active
    # ------------------------------------------------------------------

    update_subscription_status(
        subscription["subscription_id"],
        "active",
    )

    # ------------------------------------------------------------------
    # Payment captured event
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
                f"Payment {payment_id} captured successfully."
            ),
        }
    )

    # ------------------------------------------------------------------
    # Invoice paid event
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
                f"Invoice {invoice['invoice_id']} marked paid."
            ),
        }
    )

    # ------------------------------------------------------------------
    # Authoritative recovery event
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
                f"₹{amount / 100:,.2f} recovery confirmed from "
                f"payment {payment_id}."
            ),
        }
    )


# ============================================================================
# BATCH METRICS
# ============================================================================

def _refresh_batch_recovery_totals(
    batch_id: str,
) -> None:
    """
    Recalculate batch outcome counters.

    Recovered revenue comes only from recovery_confirmed events.
    """

    batch = get_batch_run(
        batch_id
    )

    if not batch:
        return

    from backend.data.db import get_revenue_events

    recovery_events = get_revenue_events(
        batch_id=batch_id,
        event_type="recovery_confirmed",
    )

    recovered_invoice_ids = {
        event["invoice_id"]
        for event in recovery_events
        if event.get("invoice_id")
    }

    amount_recovered = sum(
        int(event.get("amount", 0))
        for event in recovery_events
    )

    invoices = get_invoices(
        batch_id=batch_id
    )

    recovered_count = len(
        recovered_invoice_ids
    )

    exhausted_count = 0
    in_progress_count = 0
    manual_review_count = 0

    for invoice in invoices:

        invoice_id = invoice["invoice_id"]

        # Already recovered.
        if invoice_id in recovered_invoice_ids:
            continue

        category = invoice.get(
            "failure_category"
        )

        # Unknown failures remain manual review.
        if category == "unclassified":
            manual_review_count += 1
            continue

        actions = get_recovery_actions(
            invoice_id=invoice_id
        )

        # A blocked action remains outside the automated active pipeline.
        if any(
            action.get("status") == "blocked"
            for action in actions
        ):
            continue

        retry_count = _automated_retry_count(
            invoice_id
        )

        if retry_count >= MAX_AUTOMATED_PAYMENT_RETRIES:
            exhausted_count += 1
        else:
            in_progress_count += 1

    update_batch_run(
        batch_id,
        amount_recovered=amount_recovered,
        recovered_count=recovered_count,
        exhausted_count=exhausted_count,
        in_progress_count=in_progress_count,
        manual_review_count=manual_review_count,
    )


# ============================================================================
# CUSTOMER-ACTION EXECUTION
# ============================================================================

def _execute_customer_action(
    action: dict,
    invoice: dict,
    subscription: dict,
) -> dict:
    """
    Execute a customer-facing recovery action.

    This does NOT recover money.

    Result:
        awaiting_customer
    """

    executed_at = _now()

    action_type = action[
        "action_type"
    ]

    customer_name = subscription.get(
        "customer_name"
    ) or "customer"

    if action_type == "payment_method_update":

        detail = (
            f"Payment-method update flow prepared for "
            f"{customer_name} for invoice "
            f"{invoice['invoice_id']}."
        )

    else:

        detail = (
            f"Customer-action flow prepared for "
            f"{customer_name} for invoice "
            f"{invoice['invoice_id']}."
        )

    update_recovery_action(
        action["action_id"],
        status="awaiting_customer",
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
            "stage": "execute",
            "failure_category": invoice.get(
                "failure_category"
            ),
            "action_taken": action_type,
            "guardrail_hit": None,
            "result": "sent",
            "detail": (
                f"{detail} "
                f"Execution mode: {EXECUTION_MODE}. "
                "No revenue is counted as recovered."
            ),
        }
    )

    return {
        "action_id": action["action_id"],
        "invoice_id": invoice["invoice_id"],
        "action_type": action_type,
        "status": "awaiting_customer",
        "result": "sent",
        "recovered": False,
        "amount_recovered": 0,
        "detail": detail,
    }


# ============================================================================
# PAYMENT RETRY EXECUTION
# ============================================================================

def _execute_payment_retry(
    action: dict,
    invoice: dict,
    subscription: dict,
    *,
    as_of=None,
) -> dict:
    """
    Execute one DunnFlow recovery payment attempt.

    `as_of` is the virtual/demo clock.

    When provided, all execution timestamps generated by this function
    use `as_of` instead of wall-clock time.

    Tracks both:
        payment_attempt_number
        recovery_attempt_number
    """

    executed_at = as_of or _now()

    payment_attempt_number = (
        _next_payment_attempt_number(
            invoice["invoice_id"]
        )
    )

    recovery_attempt_number = (
        _automated_retry_count(
            invoice["invoice_id"]
        )
        + 1
    )

    # ------------------------------------------------------------------
    # RETRY-BUDGET GUARDRAIL
    # ------------------------------------------------------------------
    # Authorization must happen BEFORE gateway simulation or payment
    # attempt creation. An exhausted retry budget must never create
    # another payment attempt.
    if recovery_attempt_number > MAX_AUTOMATED_PAYMENT_RETRIES:

        guardrail_hit = (
            "max_automated_payment_retries_exceeded"
        )

        detail = (
            f"Recovery attempt #{recovery_attempt_number} was blocked. "
            f"The automated retry budget of "
            f"{MAX_AUTOMATED_PAYMENT_RETRIES} "
            "has already been exhausted. "
            "No payment attempt was created."
        )

        update_subscription_status(
            subscription["subscription_id"],
            "halted",
            retry_count=MAX_AUTOMATED_PAYMENT_RETRIES,
        )

        update_recovery_action(
            action["action_id"],
            status="blocked",
            executed_at=executed_at,
            guardrail_hit=guardrail_hit,
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
                "stage": "guardrail_block",
                "failure_category": invoice.get(
                    "failure_category"
                ),
                "action_taken": action[
                    "action_type"
                ],
                "guardrail_hit": guardrail_hit,
                "result": "blocked",
                "detail": detail,
            }
        )

        return {
            "action_id": action["action_id"],
            "invoice_id": invoice["invoice_id"],
            "action_type": action["action_type"],
            "payment_attempt_number": payment_attempt_number,
            "recovery_attempt_number": recovery_attempt_number,
            "attempt_id": None,
            "result": "blocked",
            "status": "blocked",
            "recovered": False,
            "amount_recovered": 0,
            "payment_id": None,
            "detail": detail,
        }

    gateway_result = _simulate_payment_attempt(
        invoice,
        subscription,
        recovery_attempt_number,
    )

    attempt_result = (
        "success"
        if gateway_result["status"] == "captured"
        else "failed"
    )

    payment_id = (
        f"pay_test_dunnflow_"
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
            "attempt_type": "recovery_payment",
            "action_type": action[
                "action_type"
            ],
            "scheduled_for": action.get(
                "scheduled_for"
            ),
            "executed_at": executed_at,
            "result": attempt_result,
            "raw_error_code": gateway_result.get(
                "raw_error_code"
            ),
            "failure_reason": gateway_result.get(
                "failure_reason"
            ),
            "gateway_status": gateway_result.get(
                "gateway_status"
            ),
            "result_detail": gateway_result.get(
                "message"
            ),
            "created_at": executed_at,
        }
    )

    # ------------------------------------------------------------------
    # SUCCESS
    # ------------------------------------------------------------------

    if attempt_result == "success":

        _record_successful_recovery(
            invoice=invoice,
            subscription=subscription,
            attempt_id=attempt_id,
            payment_id=payment_id,
            executed_at=executed_at,
        )

        update_recovery_action(
            action["action_id"],
            status="executed",
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
                    f"Payment history attempt "
                    f"#{payment_attempt_number} succeeded. "
                    f"DunnFlow recovery attempt "
                    f"#{recovery_attempt_number} of "
                    f"{MAX_AUTOMATED_PAYMENT_RETRIES}. "
                    f"₹{invoice['amount'] / 100:,.2f} "
                    "confirmed recovered. "
                    f"Execution mode: {EXECUTION_MODE}."
                ),
            }
        )

        _refresh_batch_recovery_totals(
            invoice["batch_id"]
        )

        return {
            "action_id": action["action_id"],
            "invoice_id": invoice["invoice_id"],
            "action_type": action[
                "action_type"
            ],
            "payment_attempt_number": payment_attempt_number,
            "recovery_attempt_number": recovery_attempt_number,
            "attempt_id": attempt_id,
            "result": "success",
            "status": "recovered",
            "recovered": True,
            "amount_recovered": invoice[
                "amount"
            ],
            "payment_id": payment_id,
            "detail": gateway_result[
                "message"
            ],
        }

    # ------------------------------------------------------------------
    # FAILURE
    # ------------------------------------------------------------------

    retry_count = _automated_retry_count(
        invoice["invoice_id"]
    )

    if retry_count >= MAX_AUTOMATED_PAYMENT_RETRIES:

        result_status = "exhausted"

        guardrail_hit = (
            "max_automated_payment_retries_exceeded"
        )

        update_subscription_status(
            subscription["subscription_id"],
            "halted",
            retry_count=retry_count,
        )

        detail = (
            f"DunnFlow recovery attempt "
            f"#{recovery_attempt_number} failed. "
            f"The automated retry budget of "
            f"{MAX_AUTOMATED_PAYMENT_RETRIES} "
            "has been exhausted. "
            "Further automated retries are prohibited."
        )

    else:

        result_status = "pending"

        guardrail_hit = None

        update_subscription_status(
            subscription["subscription_id"],
            "pending",
            retry_count=retry_count,
        )

        detail = (
            f"DunnFlow recovery attempt "
            f"#{recovery_attempt_number} failed. "
            f"{retry_count}/"
            f"{MAX_AUTOMATED_PAYMENT_RETRIES} "
            "automated recovery attempts have been used."
        )

    update_invoice_status(
        invoice["invoice_id"],
        "issued",
    )

    update_recovery_action(
        action["action_id"],
        status="executed",
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
            "guardrail_hit": guardrail_hit,
            "result": "failed",
            "detail": (
                f"{detail} "
                f"Gateway result: "
                f"{gateway_result['message']} "
                f"Execution mode: {EXECUTION_MODE}."
            ),
        }
    )

    _refresh_batch_recovery_totals(
        invoice["batch_id"]
    )

    return {
        "action_id": action["action_id"],
        "invoice_id": invoice["invoice_id"],
        "action_type": action[
            "action_type"
        ],
        "payment_attempt_number": payment_attempt_number,
        "recovery_attempt_number": recovery_attempt_number,
        "attempt_id": attempt_id,
        "result": "failed",
        "status": result_status,
        "recovered": False,
        "amount_recovered": 0,
        "payment_id": payment_id,
        "detail": gateway_result[
            "message"
        ],
    }


# ============================================================================
# REAL RAZORPAY TEST-MODE EXECUTION
# ============================================================================

def _execute_razorpay_payment(
    action: dict,
    invoice: dict,
    subscription: dict,
    *,
    as_of=None,
) -> dict:
    """Create one real Razorpay Test Mode order for a DunnFlow recovery."""

    executed_at = as_of or _now()

    if isinstance(executed_at, str):
        executed_at = datetime.fromisoformat(
            executed_at.replace("Z", "+00:00")
        )

    payment_attempt_number = _next_payment_attempt_number(
        invoice["invoice_id"]
    )

    recovery_attempt_number = (
        _automated_retry_count(
            invoice["invoice_id"]
        )
        + 1
    )

    # ------------------------------------------------------------------
    # RETRY-BUDGET GUARDRAIL
    # ------------------------------------------------------------------
    # Authorization must happen BEFORE creating a Razorpay order.
    if recovery_attempt_number > MAX_AUTOMATED_PAYMENT_RETRIES:

        guardrail_hit = (
            "max_automated_payment_retries_exceeded"
        )

        detail = (
            f"Recovery attempt #{recovery_attempt_number} was blocked. "
            f"The automated retry budget of "
            f"{MAX_AUTOMATED_PAYMENT_RETRIES} "
            "has already been exhausted. "
            "No Razorpay order or payment attempt was created."
        )

        update_subscription_status(
            subscription["subscription_id"],
            "halted",
            retry_count=MAX_AUTOMATED_PAYMENT_RETRIES,
        )

        update_recovery_action(
            action["action_id"],
            status="blocked",
            executed_at=executed_at,
            guardrail_hit=guardrail_hit,
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
                "stage": "guardrail_block",
                "failure_category": invoice.get(
                    "failure_category"
                ),
                "action_taken": action[
                    "action_type"
                ],
                "guardrail_hit": guardrail_hit,
                "result": "blocked",
                "detail": detail,
            }
        )

        return {
            "action_id": action["action_id"],
            "invoice_id": invoice["invoice_id"],
            "action_type": action["action_type"],
            "payment_attempt_number": payment_attempt_number,
            "recovery_attempt_number": recovery_attempt_number,
            "attempt_id": None,
            "result": "blocked",
            "status": "blocked",
            "recovered": False,
            "amount_recovered": 0,
            "razorpay_order_id": None,
            "detail": detail,
        }

    client = RazorpayClient()

    try:
        order = client.create_order(
            amount=int(invoice["amount"]),
            currency="INR",
            receipt=(
                f"dunnflow_{invoice['invoice_id']}_"
                f"{payment_attempt_number}"
            ),
            notes={
                "dunnflow_invoice_id": str(invoice["invoice_id"]),
                "dunnflow_subscription_id": str(
                    subscription["subscription_id"]
                ),
                "dunnflow_batch_id": str(invoice["batch_id"]),
            },
        )
    except RazorpayAPIError as exc:
        retry_at = executed_at + timedelta(minutes=30)

        update_recovery_action(
            action["action_id"],
            status="planned",
            scheduled_for=retry_at.isoformat(),
            guardrail_hit="razorpay_gateway_unavailable",
        )

        log_audit_entry(
            {
                "batch_id": invoice["batch_id"],
                "subscription_id": subscription["subscription_id"],
                "invoice_id": invoice["invoice_id"],
                "payment_attempt_id": None,
                "stage": "execute",
                "failure_category": invoice.get("failure_category"),
                "action_taken": action["action_type"],
                "guardrail_hit": "razorpay_gateway_unavailable",
                "result": "retry_scheduled",
                "detail": (
                    "Razorpay was unavailable while creating the recovery order. "
                    f"Retry scheduled for {retry_at.isoformat()}. "
                    f"Gateway error: {exc}"
                ),
            }
        )

        return {
            "action_id": action["action_id"],
            "invoice_id": invoice["invoice_id"],
            "action_type": action["action_type"],
            "payment_attempt_number": payment_attempt_number,
            "attempt_id": None,
            "result": "retry_scheduled",
            "status": "planned",
            "recovered": False,
            "amount_recovered": 0,
            "razorpay_order_id": None,
            "detail": (
                "Razorpay is temporarily unavailable. "
                "No payment attempt was created; recovery was rescheduled "
                f"for {retry_at.isoformat()}."
            ),
        }

    razorpay_order_id = order["id"]

    attach_razorpay_order_to_invoice(
        invoice["invoice_id"],
        razorpay_order_id,
    )

    attempt_id = create_payment_attempt(
        {
            "batch_id": invoice["batch_id"],
            "invoice_id": invoice["invoice_id"],
            "subscription_id": subscription["subscription_id"],
            "razorpay_payment_id": None,
            "attempt_number": payment_attempt_number,
            "attempt_type": "external_razorpay",
            "action_type": action["action_type"],
            "scheduled_for": action.get("scheduled_for"),
            "executed_at": executed_at,
            "result": "pending",
            "raw_error_code": None,
            "failure_reason": None,
            "gateway_status": "created",
            "result_detail": (
                f"Razorpay order {razorpay_order_id} created; "
                "awaiting customer payment."
            ),
            "created_at": executed_at,
        }
    )

    update_recovery_action(
        action["action_id"],
        status="executed",
        executed_at=executed_at,
    )

    log_audit_entry(
        {
            "batch_id": invoice["batch_id"],
            "subscription_id": subscription["subscription_id"],
            "invoice_id": invoice["invoice_id"],
            "payment_attempt_id": attempt_id,
            "stage": "execute",
            "failure_category": invoice.get("failure_category"),
            "action_taken": action["action_type"],
            "guardrail_hit": None,
            "result": "pending",
            "detail": (
                f"Razorpay Test Mode order "
                f"{razorpay_order_id} created for "
                f"INR {invoice['amount'] / 100:,.2f}. "
                "Awaiting customer payment."
            ),
        }
    )

    return {
        "action_id": action["action_id"],
        "invoice_id": invoice["invoice_id"],
        "action_type": action["action_type"],
        "payment_attempt_number": payment_attempt_number,
        "attempt_id": attempt_id,
        "result": "pending",
        "status": "awaiting_payment",
        "recovered": False,
        "amount_recovered": 0,
        "razorpay_order_id": razorpay_order_id,
        "razorpay_key_id": client.key_id,
        "amount": int(invoice["amount"]),
        "currency": "INR",
        "detail": (
            "Razorpay Test Mode order created. "
            "Customer payment is required to complete recovery."
        ),
    }


# ============================================================================
# EXECUTE ONE ACTION
# ============================================================================

def execute_recovery_action(
    action_id: int,
    *,
    as_of=None,
) -> dict:
    """
    Execute exactly one planned recovery action.

    `as_of` is the virtual/demo clock.

    When provided, execution timestamps use `as_of` rather than wall-clock
    time. This keeps scheduler and execution deterministic during demos/tests.
    """

    execution_time = as_of or _now()

    action = get_recovery_action(
        action_id
    )

    if not action:

        return {
            "action_id": action_id,
            "status": "invalid",
            "result": "failed",
            "recovered": False,
            "detail": "Recovery action does not exist.",
        }

    invoice = None

    if action.get("invoice_id"):

        invoice = get_invoice(
            action["invoice_id"]
        )

    subscription = get_subscription(
        action["subscription_id"]
    )

    # ------------------------------------------------------------------
    # Missing context
    # ------------------------------------------------------------------

    if not invoice or not subscription:

        update_recovery_action(
            action_id,
            status="blocked",
            executed_at=execution_time,
            guardrail_hit="recovery_context_missing",
        )

        log_audit_entry(
            {
                "batch_id": action["batch_id"],
                "subscription_id": action[
                    "subscription_id"
                ],
                "invoice_id": action.get(
                    "invoice_id"
                ),
                "payment_attempt_id": None,
                "stage": "guardrail_block",
                "failure_category": (
                    invoice.get(
                        "failure_category"
                    )
                    if invoice
                    else None
                ),
                "action_taken": action[
                    "action_type"
                ],
                "guardrail_hit": (
                    "recovery_context_missing"
                ),
                "result": "blocked",
                "detail": (
                    "Execution refused because the required "
                    "invoice or subscription context is missing."
                ),
            }
        )

        return {
            "action_id": action_id,
            "status": "blocked",
            "result": "failed",
            "recovered": False,
            "detail": (
                "Invoice or subscription context is missing."
            ),
        }

    # ------------------------------------------------------------------
    # Invoice already paid
    # ------------------------------------------------------------------

    if invoice["status"] == "paid":

        update_recovery_action(
            action_id,
            status="cancelled",
            executed_at=execution_time,
            guardrail_hit="invoice_already_paid",
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
                "stage": "guardrail_block",
                "failure_category": invoice.get(
                    "failure_category"
                ),
                "action_taken": action[
                    "action_type"
                ],
                "guardrail_hit": "invoice_already_paid",
                "result": "blocked",
                "detail": (
                    "Execution cancelled because the invoice "
                    "is already paid."
                ),
            }
        )

        return {
            "action_id": action_id,
            "status": "cancelled",
            "result": "blocked",
            "recovered": False,
            "detail": "Invoice is already paid.",
        }

    # ------------------------------------------------------------------
    # Only planned actions can execute.
    # ------------------------------------------------------------------

    if action["status"] != "planned":

        return {
            "action_id": action_id,
            "status": action["status"],
            "result": "not_executed",
            "recovered": False,
            "detail": (
                f"Action status is '{action['status']}'. "
                "Execution skipped."
            ),
        }

    # ------------------------------------------------------------------
    # Manual review / no action
    # ------------------------------------------------------------------

    if action["action_type"] in NON_EXECUTABLE_ACTIONS:

        update_recovery_action(
            action_id,
            status="cancelled",
            executed_at=execution_time,
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
                "stage": "execute",
                "failure_category": invoice.get(
                    "failure_category"
                ),
                "action_taken": action[
                    "action_type"
                ],
                "guardrail_hit": None,
                "result": "not_executed",
                "detail": (
                    f"Action '{action['action_type']}' "
                    "is not an automated executable action."
                ),
            }
        )

        return {
            "action_id": action_id,
            "status": "cancelled",
            "result": "not_executed",
            "recovered": False,
            "detail": (
                "Manual review does not execute automatically."
            ),
        }

    # ------------------------------------------------------------------
    # Customer-facing recovery
    # ------------------------------------------------------------------

    if action["action_type"] in CUSTOMER_ACTIONS:

        return _execute_customer_action(
            action=action,
            invoice=invoice,
            subscription=subscription,
        )

    # ------------------------------------------------------------------
    # Payment recovery
    # ------------------------------------------------------------------

    if action["action_type"] in PAYMENT_RETRY_ACTIONS:

        if EXECUTION_MODE == "razorpay_test_mode":

            return _execute_razorpay_payment(
                action=action,
                invoice=invoice,
                subscription=subscription,
                as_of=as_of,
            )

        return _execute_payment_retry(
            action=action,
            invoice=invoice,
            subscription=subscription,
            as_of=as_of,
        )

    # ------------------------------------------------------------------
    # Unsupported action
    # ------------------------------------------------------------------

    update_recovery_action(
        action_id,
        status="blocked",
        executed_at=execution_time,
        guardrail_hit="unsupported_action_type",
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
            "stage": "guardrail_block",
            "failure_category": invoice.get(
                "failure_category"
            ),
            "action_taken": action[
                "action_type"
            ],
            "guardrail_hit": "unsupported_action_type",
            "result": "blocked",
            "detail": (
                f"Execution refused because action type "
                f"'{action['action_type']}' is unsupported."
            ),
        }
    )

    return {
        "action_id": action_id,
        "status": "blocked",
        "result": "failed",
        "recovered": False,
        "detail": (
            f"Unsupported action type "
            f"'{action['action_type']}'."
        ),
    }


# ============================================================================
# EXECUTE ONLY DUE ACTIONS
# ============================================================================

def execute_due_actions(
    batch_id: str,
    *,
    as_of=None,
) -> dict:
    """
    Execute ONLY actions that scheduler.py says are due.

    `as_of` is the virtual/demo clock.

    The same virtual timestamp is passed into each action execution.
    """

    from backend.modules.scheduler import get_due_actions

    due_actions = get_due_actions(
        batch_id=batch_id,
        as_of=as_of,
    )

    results = []

    for action in due_actions:

        result = execute_recovery_action(
            action["action_id"],
            as_of=as_of,
        )

        results.append(
            result
        )

    _refresh_batch_recovery_totals(
        batch_id
    )

    metrics = get_batch_metrics(
        batch_id
    )

    return {
        "batch_id": batch_id,
        "execution_mode": EXECUTION_MODE,
        "as_of": (
            as_of.isoformat(
                timespec="seconds"
            )
            if as_of
            else _now()
        ),
        "due_actions_found": len(
            due_actions
        ),
        "actions_executed": len(
            results
        ),
        "results": results,
        "metrics": metrics,
    }


# ============================================================================
# DEMO-CLOCK EXECUTION
# ============================================================================

def execute_demo_stage(
    batch_id: str,
    stage: str,
) -> dict:

    from backend.modules.scheduler import (
        get_batch_demo_timestamps,
    )

    timestamps = get_batch_demo_timestamps(
        batch_id
    )

    if stage == "now":
        demo_time = timestamps["now"]

    elif stage == "one_hour":
        demo_time = timestamps["one_hour"]

    elif stage == "one_day":
        demo_time = timestamps["one_day"]

    else:
        raise ValueError(
            "Unknown demo stage. "
            "Use 'now', 'one_hour', or 'one_day'."
        )

    return execute_due_actions(
        batch_id,
        as_of=demo_time,
    )


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

    report = execute_due_actions(
        batch_id
    )

    print()
    print("=" * 68)
    print("DUNNFLOW DUE-ACTION EXECUTION")
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
        f"Checked at:           "
        f"{report['as_of']}"
    )

    print(
        f"Due actions found:    "
        f"{report['due_actions_found']}"
    )

    print(
        f"Actions executed:     "
        f"{report['actions_executed']}"
    )

    metrics = report[
        "metrics"
    ]

    print()
    print("Financial result:")

    print(
        f"  Amount at risk:     "
        f"₹{metrics['amount_at_risk'] / 100:,.2f}"
    )

    print(
        f"  Amount recovered:   "
        f"₹{metrics['amount_recovered'] / 100:,.2f}"
    )

    print(
        f"  Recovery rate:      "
        f"{metrics['recovery_rate_pct']}%"
    )

    print(
        f"  Guardrail blocks:   "
        f"{metrics['guardrail_blocks']}"
    )

    print()
    print("=" * 68)