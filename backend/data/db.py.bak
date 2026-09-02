"""
DunnFlow data-access layer.

All database access is centralized here. Business modules should never
contain raw SQL; they should call these functions instead.

Domain model:

    batch_run
        └── subscription
                └── invoice
                        └── payment_attempt
                └── recovery_action
        └── revenue_event
        └── audit_log

SQLite is used for the buildathon demo, but keeping DB access behind this
module makes the application easier to move to PostgreSQL later.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlite3


# ---------------------------------------------------------------------------
# Paths / time
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).resolve().parents[2] / "dunnflow.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _now() -> str:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

@contextmanager
def get_conn():
    """
    Open a SQLite connection with foreign keys enabled.

    The transaction is committed when the context exits normally and rolled
    back automatically if an exception escapes the context.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """
    Create all required tables/indexes.

    Safe to call repeatedly because schema.sql uses IF NOT EXISTS.
    """
    with get_conn() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _fetchone(query: str, params: tuple[Any, ...] = ()) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None


def _fetchall(query: str, params: tuple[Any, ...] = ()) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


# ===========================================================================
# BATCH RUNS
# ===========================================================================

def create_batch_run(
    batch_id: str,
    *,
    started_at: str | None = None,
    status: str = "running",
) -> None:
    """Create a new benchmark/demo batch."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO batch_runs (
                batch_id,
                started_at,
                status
            )
            VALUES (?, ?, ?)
            """,
            (
                batch_id,
                started_at or _now(),
                status,
            ),
        )


def get_batch_run(batch_id: str) -> dict | None:
    """Return one batch run."""
    return _fetchone(
        """
        SELECT *
        FROM batch_runs
        WHERE batch_id = ?
        """,
        (batch_id,),
    )


def list_batch_runs(limit: int = 20) -> list[dict]:
    """Return recent batch runs."""
    return _fetchall(
        """
        SELECT *
        FROM batch_runs
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (limit,),
    )


def update_batch_run(
    batch_id: str,
    *,
    status: str | None = None,
    completed_at: str | None = None,
    total_subscriptions: int | None = None,
    total_invoices: int | None = None,
    amount_at_risk: int | None = None,
    amount_recovered: int | None = None,
    recovered_count: int | None = None,
    exhausted_count: int | None = None,
    in_progress_count: int | None = None,
    manual_review_count: int | None = None,
) -> None:
    """
    Update whichever batch fields are supplied.

    This avoids multiple specialized update functions while still keeping
    SQL out of the rest of the application.
    """
    updates: list[str] = []
    values: list[Any] = []

    fields = {
        "status": status,
        "completed_at": completed_at,
        "total_subscriptions": total_subscriptions,
        "total_invoices": total_invoices,
        "amount_at_risk": amount_at_risk,
        "amount_recovered": amount_recovered,
        "recovered_count": recovered_count,
        "exhausted_count": exhausted_count,
        "in_progress_count": in_progress_count,
        "manual_review_count": manual_review_count,
    }

    for column, value in fields.items():
        if value is not None:
            updates.append(f"{column} = ?")
            values.append(value)

    if not updates:
        return

    values.append(batch_id)

    with get_conn() as conn:
        conn.execute(
            f"""
            UPDATE batch_runs
            SET {", ".join(updates)}
            WHERE batch_id = ?
            """,
            tuple(values),
        )


# ===========================================================================
# SUBSCRIPTIONS
# ===========================================================================

def upsert_subscription(subscription: dict) -> None:
    """
    Insert or update a subscription.

    `subscription_id` is DunnFlow's internal stable identifier.
    `razorpay_subscription_id` stores the corresponding Razorpay identifier
    when available.
    """
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO subscriptions (
                subscription_id,
                batch_id,
                razorpay_subscription_id,
                customer_id,
                customer_name,
                customer_email,
                plan_id,
                plan_name,
                amount,
                currency,
                status,
                current_cycle,
                total_cycles,
                retry_count,
                last_failure_category,
                created_at,
                updated_at
            )
            VALUES (
                :subscription_id,
                :batch_id,
                :razorpay_subscription_id,
                :customer_id,
                :customer_name,
                :customer_email,
                :plan_id,
                :plan_name,
                :amount,
                :currency,
                :status,
                :current_cycle,
                :total_cycles,
                :retry_count,
                :last_failure_category,
                :created_at,
                :updated_at
            )
            ON CONFLICT(subscription_id) DO UPDATE SET
                razorpay_subscription_id = excluded.razorpay_subscription_id,
                customer_name = excluded.customer_name,
                customer_email = excluded.customer_email,
                plan_id = excluded.plan_id,
                plan_name = excluded.plan_name,
                amount = excluded.amount,
                currency = excluded.currency,
                status = excluded.status,
                current_cycle = excluded.current_cycle,
                total_cycles = excluded.total_cycles,
                retry_count = excluded.retry_count,
                last_failure_category = excluded.last_failure_category,
                updated_at = excluded.updated_at
            """,
            {
                "subscription_id": subscription["subscription_id"],
                "batch_id": subscription["batch_id"],
                "razorpay_subscription_id": subscription.get(
                    "razorpay_subscription_id"
                ),
                "customer_id": subscription["customer_id"],
                "customer_name": subscription.get("customer_name"),
                "customer_email": subscription.get("customer_email"),
                "plan_id": subscription.get("plan_id"),
                "plan_name": subscription.get("plan_name"),
                "amount": subscription["amount"],
                "currency": subscription.get("currency", "INR"),
                "status": subscription.get("status", "active"),
                "current_cycle": subscription.get("current_cycle", 1),
                "total_cycles": subscription.get("total_cycles"),
                "retry_count": subscription.get("retry_count", 0),
                "last_failure_category": subscription.get(
                    "last_failure_category"
                ),
                "created_at": subscription.get("created_at", _now()),
                "updated_at": subscription.get("updated_at", _now()),
            },
        )


def get_subscription(subscription_id: str) -> dict | None:
    """Return one subscription by DunnFlow ID."""
    return _fetchone(
        """
        SELECT *
        FROM subscriptions
        WHERE subscription_id = ?
        """,
        (subscription_id,),
    )


def get_subscription_by_razorpay_id(
    razorpay_subscription_id: str,
) -> dict | None:
    """Return one subscription by Razorpay subscription ID."""
    return _fetchone(
        """
        SELECT *
        FROM subscriptions
        WHERE razorpay_subscription_id = ?
        """,
        (razorpay_subscription_id,),
    )


def get_subscriptions(
    *,
    batch_id: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """Return subscriptions, optionally filtered by batch and status."""
    conditions: list[str] = []
    params: list[Any] = []

    if batch_id is not None:
        conditions.append("batch_id = ?")
        params.append(batch_id)

    if status is not None:
        conditions.append("status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    return _fetchall(
        f"""
        SELECT *
        FROM subscriptions
        {where}
        ORDER BY created_at DESC
        """,
        tuple(params),
    )


def update_subscription_status(
    subscription_id: str,
    status: str,
    *,
    retry_count: int | None = None,
    last_failure_category: str | None = None,
) -> None:
    """Update subscription lifecycle state."""
    updates = ["status = ?", "updated_at = ?"]
    values: list[Any] = [status, _now()]

    if retry_count is not None:
        updates.append("retry_count = ?")
        values.append(retry_count)

    if last_failure_category is not None:
        updates.append("last_failure_category = ?")
        values.append(last_failure_category)

    values.append(subscription_id)

    with get_conn() as conn:
        conn.execute(
            f"""
            UPDATE subscriptions
            SET {", ".join(updates)}
            WHERE subscription_id = ?
            """,
            tuple(values),
        )


# ===========================================================================
# INVOICES
# ===========================================================================

def upsert_invoice(invoice: dict) -> None:
    """Insert or update an invoice."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO invoices (
                invoice_id,
                batch_id,
                subscription_id,
                razorpay_invoice_id,
                amount,
                currency,
                status,
                issued_at,
                paid_at,
                due_at,
                failure_category,
                created_at,
                updated_at
            )
            VALUES (
                :invoice_id,
                :batch_id,
                :subscription_id,
                :razorpay_invoice_id,
                :amount,
                :currency,
                :status,
                :issued_at,
                :paid_at,
                :due_at,
                :failure_category,
                :created_at,
                :updated_at
            )
            ON CONFLICT(invoice_id) DO UPDATE SET
                razorpay_invoice_id = excluded.razorpay_invoice_id,
                amount = excluded.amount,
                currency = excluded.currency,
                status = excluded.status,
                paid_at = excluded.paid_at,
                due_at = excluded.due_at,
                failure_category = excluded.failure_category,
                updated_at = excluded.updated_at
            """,
            {
                "invoice_id": invoice["invoice_id"],
                "batch_id": invoice["batch_id"],
                "subscription_id": invoice["subscription_id"],
                "razorpay_invoice_id": invoice.get("razorpay_invoice_id"),
                "amount": invoice["amount"],
                "currency": invoice.get("currency", "INR"),
                "status": invoice.get("status", "issued"),
                "issued_at": invoice.get("issued_at", _now()),
                "paid_at": invoice.get("paid_at"),
                "due_at": invoice.get("due_at"),
                "failure_category": invoice.get("failure_category"),
                "created_at": invoice.get("created_at", _now()),
                "updated_at": invoice.get("updated_at", _now()),
            },
        )


def get_invoice(invoice_id: str) -> dict | None:
    """Return one invoice."""
    return _fetchone(
        """
        SELECT *
        FROM invoices
        WHERE invoice_id = ?
        """,
        (invoice_id,),
    )


def get_invoice_by_razorpay_id(
    razorpay_invoice_id: str,
) -> dict | None:
    """Return one invoice by Razorpay invoice ID."""
    return _fetchone(
        """
        SELECT *
        FROM invoices
        WHERE razorpay_invoice_id = ?
        """,
        (razorpay_invoice_id,),
    )


def get_invoices(
    *,
    batch_id: str | None = None,
    subscription_id: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """Return invoices with optional filters."""
    conditions: list[str] = []
    params: list[Any] = []

    if batch_id is not None:
        conditions.append("batch_id = ?")
        params.append(batch_id)

    if subscription_id is not None:
        conditions.append("subscription_id = ?")
        params.append(subscription_id)

    if status is not None:
        conditions.append("status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    return _fetchall(
        f"""
        SELECT *
        FROM invoices
        {where}
        ORDER BY issued_at DESC
        """,
        tuple(params),
    )


def update_invoice_status(
    invoice_id: str,
    status: str,
    *,
    paid_at: str | None = None,
    failure_category: str | None = None,
) -> None:
    """Update invoice status and payment metadata."""
    updates = ["status = ?", "updated_at = ?"]
    values: list[Any] = [status, _now()]

    if paid_at is not None:
        updates.append("paid_at = ?")
        values.append(paid_at)

    if failure_category is not None:
        updates.append("failure_category = ?")
        values.append(failure_category)

    values.append(invoice_id)

    with get_conn() as conn:
        conn.execute(
            f"""
            UPDATE invoices
            SET {", ".join(updates)}
            WHERE invoice_id = ?
            """,
            tuple(values),
        )


# ===========================================================================
# PAYMENT ATTEMPTS
# ===========================================================================

def create_payment_attempt(attempt: dict) -> int:
    """Create one payment/recovery attempt and return its ID."""
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO payment_attempts (
                batch_id,
                invoice_id,
                subscription_id,
                razorpay_payment_id,
                attempt_number,
                attempt_type,
                action_type,
                scheduled_for,
                executed_at,
                result,
                raw_error_code,
                failure_reason,
                gateway_status,
                result_detail,
                created_at
            )
            VALUES (
                :batch_id,
                :invoice_id,
                :subscription_id,
                :razorpay_payment_id,
                :attempt_number,
                :attempt_type,
                :action_type,
                :scheduled_for,
                :executed_at,
                :result,
                :raw_error_code,
                :failure_reason,
                :gateway_status,
                :result_detail,
                :created_at
            )
            """,
            {
                "batch_id": attempt["batch_id"],
                "invoice_id": attempt["invoice_id"],
                "subscription_id": attempt["subscription_id"],
                "razorpay_payment_id": attempt.get("razorpay_payment_id"),
                "attempt_number": attempt["attempt_number"],
                "attempt_type": attempt["attempt_type"],
                "action_type": attempt.get("action_type"),
                "scheduled_for": attempt.get("scheduled_for"),
                "executed_at": attempt.get("executed_at"),
                "result": attempt.get("result"),
                "raw_error_code": attempt.get("raw_error_code"),
                "failure_reason": attempt.get("failure_reason"),
                "gateway_status": attempt.get("gateway_status"),
                "result_detail": attempt.get("result_detail"),
                "created_at": attempt.get("created_at", _now()),
            },
        )
        return int(cur.lastrowid)


def get_payment_attempt(attempt_id: int) -> dict | None:
    """Return one payment attempt."""
    return _fetchone(
        """
        SELECT *
        FROM payment_attempts
        WHERE attempt_id = ?
        """,
        (attempt_id,),
    )


def get_payment_attempts(
    *,
    invoice_id: str | None = None,
    subscription_id: str | None = None,
    batch_id: str | None = None,
) -> list[dict]:
    """Return payment attempts with optional filters."""
    conditions: list[str] = []
    params: list[Any] = []

    if invoice_id is not None:
        conditions.append("invoice_id = ?")
        params.append(invoice_id)

    if subscription_id is not None:
        conditions.append("subscription_id = ?")
        params.append(subscription_id)

    if batch_id is not None:
        conditions.append("batch_id = ?")
        params.append(batch_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    return _fetchall(
        f"""
        SELECT *
        FROM payment_attempts
        {where}
        ORDER BY attempt_number ASC, created_at ASC
        """,
        tuple(params),
    )


def count_attempts(
    invoice_id: str,
    *,
    result: str | None = None,
) -> int:
    """Count payment attempts for an invoice."""
    if result is None:
        row = _fetchone(
            """
            SELECT COUNT(*) AS count
            FROM payment_attempts
            WHERE invoice_id = ?
            """,
            (invoice_id,),
        )
    else:
        row = _fetchone(
            """
            SELECT COUNT(*) AS count
            FROM payment_attempts
            WHERE invoice_id = ?
              AND result = ?
            """,
            (invoice_id, result),
        )

    return int(row["count"]) if row else 0


# ===========================================================================
# RECOVERY ACTIONS
# ===========================================================================

def create_recovery_action(action: dict) -> int:
    """Create a planned or executed DunnFlow recovery action."""
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO recovery_actions (
                batch_id,
                subscription_id,
                invoice_id,
                action_type,
                reason,
                priority,
                scheduled_for,
                executed_at,
                status,
                guardrail_hit,
                created_at
            )
            VALUES (
                :batch_id,
                :subscription_id,
                :invoice_id,
                :action_type,
                :reason,
                :priority,
                :scheduled_for,
                :executed_at,
                :status,
                :guardrail_hit,
                :created_at
            )
            """,
            {
                "batch_id": action["batch_id"],
                "subscription_id": action["subscription_id"],
                "invoice_id": action.get("invoice_id"),
                "action_type": action["action_type"],
                "reason": action["reason"],
                "priority": action.get("priority", "normal"),
                "scheduled_for": action.get("scheduled_for"),
                "executed_at": action.get("executed_at"),
                "status": action.get("status", "planned"),
                "guardrail_hit": action.get("guardrail_hit"),
                "created_at": action.get("created_at", _now()),
            },
        )
        return int(cur.lastrowid)


def get_recovery_action(action_id: int) -> dict | None:
    """Return one recovery action."""
    return _fetchone(
        """
        SELECT *
        FROM recovery_actions
        WHERE action_id = ?
        """,
        (action_id,),
    )


def get_recovery_actions(
    *,
    batch_id: str | None = None,
    subscription_id: str | None = None,
    invoice_id: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """Return recovery actions with optional filters."""
    conditions: list[str] = []
    params: list[Any] = []

    if batch_id is not None:
        conditions.append("batch_id = ?")
        params.append(batch_id)

    if subscription_id is not None:
        conditions.append("subscription_id = ?")
        params.append(subscription_id)

    if invoice_id is not None:
        conditions.append("invoice_id = ?")
        params.append(invoice_id)

    if status is not None:
        conditions.append("status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    return _fetchall(
        f"""
        SELECT *
        FROM recovery_actions
        {where}
        ORDER BY created_at ASC
        """,
        tuple(params),
    )


def update_recovery_action(
    action_id: int,
    *,
    status: str | None = None,
    executed_at: str | None = None,
    guardrail_hit: str | None = None,
) -> None:
    """Update execution state for a recovery action."""
    updates: list[str] = []
    values: list[Any] = []

    if status is not None:
        updates.append("status = ?")
        values.append(status)

    if executed_at is not None:
        updates.append("executed_at = ?")
        values.append(executed_at)

    if guardrail_hit is not None:
        updates.append("guardrail_hit = ?")
        values.append(guardrail_hit)

    if not updates:
        return

    values.append(action_id)

    with get_conn() as conn:
        conn.execute(
            f"""
            UPDATE recovery_actions
            SET {", ".join(updates)}
            WHERE action_id = ?
            """,
            tuple(values),
        )


# ===========================================================================
# REVENUE EVENTS
# ===========================================================================

def record_revenue_event(event: dict) -> int:
    """
    Record a financial/lifecycle event.

    This table is intentionally separate from status fields because recovered
    revenue must be traceable to a concrete event.
    """
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO revenue_events (
                batch_id,
                subscription_id,
                invoice_id,
                payment_attempt_id,
                event_type,
                amount,
                razorpay_event_id,
                event_timestamp,
                detail
            )
            VALUES (
                :batch_id,
                :subscription_id,
                :invoice_id,
                :payment_attempt_id,
                :event_type,
                :amount,
                :razorpay_event_id,
                :event_timestamp,
                :detail
            )
            """,
            {
                "batch_id": event["batch_id"],
                "subscription_id": event["subscription_id"],
                "invoice_id": event.get("invoice_id"),
                "payment_attempt_id": event.get("payment_attempt_id"),
                "event_type": event["event_type"],
                "amount": event.get("amount", 0),
                "razorpay_event_id": event.get("razorpay_event_id"),
                "event_timestamp": event.get("event_timestamp", _now()),
                "detail": event.get("detail"),
            },
        )
        return int(cur.lastrowid)


def get_revenue_events(
    *,
    batch_id: str | None = None,
    invoice_id: str | None = None,
    event_type: str | None = None,
) -> list[dict]:
    """Return financial events with optional filters."""
    conditions: list[str] = []
    params: list[Any] = []

    if batch_id is not None:
        conditions.append("batch_id = ?")
        params.append(batch_id)

    if invoice_id is not None:
        conditions.append("invoice_id = ?")
        params.append(invoice_id)

    if event_type is not None:
        conditions.append("event_type = ?")
        params.append(event_type)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    return _fetchall(
        f"""
        SELECT *
        FROM revenue_events
        {where}
        ORDER BY event_timestamp ASC
        """,
        tuple(params),
    )


# ===========================================================================
# AUDIT LOG
# ===========================================================================

def log_audit_entry(entry: dict) -> int:
    """
    Write one immutable audit entry.

    Every important agent decision/action should pass through this function.
    """
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO audit_log (
                batch_id,
                subscription_id,
                invoice_id,
                payment_attempt_id,
                stage,
                failure_category,
                action_taken,
                guardrail_hit,
                result,
                detail,
                timestamp
            )
            VALUES (
                :batch_id,
                :subscription_id,
                :invoice_id,
                :payment_attempt_id,
                :stage,
                :failure_category,
                :action_taken,
                :guardrail_hit,
                :result,
                :detail,
                :timestamp
            )
            """,
            {
                "batch_id": entry["batch_id"],
                "subscription_id": entry.get("subscription_id"),
                "invoice_id": entry.get("invoice_id"),
                "payment_attempt_id": entry.get("payment_attempt_id"),
                "stage": entry["stage"],
                "failure_category": entry.get("failure_category"),
                "action_taken": entry.get("action_taken"),
                "guardrail_hit": entry.get("guardrail_hit"),
                "result": entry.get("result"),
                "detail": entry["detail"],
                "timestamp": entry.get("timestamp", _now()),
            },
        )
        return int(cur.lastrowid)


def get_audit_log(
    *,
    batch_id: str | None = None,
    subscription_id: str | None = None,
    invoice_id: str | None = None,
) -> list[dict]:
    """Return audit history, optionally scoped to one entity."""
    conditions: list[str] = []
    params: list[Any] = []

    if batch_id is not None:
        conditions.append("batch_id = ?")
        params.append(batch_id)

    if subscription_id is not None:
        conditions.append("subscription_id = ?")
        params.append(subscription_id)

    if invoice_id is not None:
        conditions.append("invoice_id = ?")
        params.append(invoice_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    return _fetchall(
        f"""
        SELECT *
        FROM audit_log
        {where}
        ORDER BY timestamp ASC, log_id ASC
        """,
        tuple(params),
    )


# ===========================================================================
# METRICS
# ===========================================================================

def get_batch_metrics(batch_id: str) -> dict:
    """
    Calculate judge-facing metrics for one benchmark batch.

    Financial truth
    ---------------
    Recovered revenue is calculated ONLY from `recovery_confirmed`
    revenue events.

    Outcome truth
    -------------
    Every invoice should end in one of these states:

        recovered
        in_progress
        exhausted
        blocked
        manual_review
    """

    batch = get_batch_run(
        batch_id
    )

    if not batch:
        return {
            "batch_id": batch_id,
            "exists": False,
        }

    # ------------------------------------------------------------------
    # Financial events
    # ------------------------------------------------------------------

    recovery_events = _fetchall(
        """
        SELECT *
        FROM revenue_events
        WHERE batch_id = ?
          AND event_type = 'recovery_confirmed'
        ORDER BY event_timestamp ASC
        """,
        (batch_id,),
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

        # ------------------------------------------------------------------
    # Current revenue at risk
    #
    # revenue_at_risk events are historical facts.
    # Current risk must be calculated from the invoice's current status.
    # A recovered/paid invoice is no longer currently at risk.
    # ------------------------------------------------------------------

    at_risk = _fetchone(
        """
        SELECT
            COUNT(*) AS invoice_count,
            COALESCE(SUM(amount), 0) AS amount
        FROM invoices
        WHERE batch_id = ?
          AND status != 'paid'
        """,
        (batch_id,),
    )

    total_invoices = int(
        at_risk["invoice_count"] or 0
    )

    amount_at_risk = int(
        at_risk["amount"] or 0
    )

    # ------------------------------------------------------------------
# Current revenue at risk
#
# revenue_at_risk events are historical facts.
# Current risk must be calculated from the invoice's current status.
# A recovered/paid invoice is no longer currently at risk.
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# All invoices in benchmark
# ------------------------------------------------------------------
    # ------------------------------------------------------------------
# Historical revenue-at-risk baseline
#
# This is the amount that was originally exposed to failure.
# It is used as the denominator for recovery rate.
# ------------------------------------------------------------------

    historical_risk = _fetchone(
    """
    SELECT
        COUNT(DISTINCT invoice_id) AS invoice_count,
        COALESCE(SUM(amount), 0) AS amount
    FROM revenue_events
    WHERE batch_id = ?
      AND event_type = 'revenue_at_risk'
    """,
    (batch_id,),
)

    historical_invoices_at_risk = int(
    historical_risk["invoice_count"] or 0
)

    historical_amount_at_risk = int(
    historical_risk["amount"] or 0
)

    invoices = get_invoices(
        batch_id=batch_id
    )

    # ------------------------------------------------------------------
    # Explicit outcome counts
    # ------------------------------------------------------------------

    recovered_count = 0
    in_progress_count = 0
    exhausted_count = 0
    blocked_count = 0
    manual_review_count = 0

    for invoice in invoices:

        invoice_id = invoice["invoice_id"]

        # --------------------------------------------------------------
        # RECOVERED
        # --------------------------------------------------------------

        if invoice_id in recovered_invoice_ids:

            recovered_count += 1
            continue

        # --------------------------------------------------------------
        # MANUAL REVIEW
        # --------------------------------------------------------------

        if invoice.get("failure_category") == "unclassified":

            manual_review_count += 1
            continue

        # --------------------------------------------------------------
        # BLOCKED
        # --------------------------------------------------------------

        actions = get_recovery_actions(
            invoice_id=invoice_id
        )

        has_blocked_action = any(
            action.get("status") == "blocked"
            for action in actions
        )

        if has_blocked_action:

            blocked_count += 1
            continue

        # --------------------------------------------------------------
        # EXHAUSTED
        # --------------------------------------------------------------

        attempts = get_payment_attempts(
            invoice_id=invoice_id
        )

        automated_retry_count = sum(
            1
            for attempt in attempts
            if attempt.get("attempt_type") in {
                "auto_retry",
                "manual_retry",
                "recovery_payment",
            }
        )

        if automated_retry_count >= 3:

            exhausted_count += 1
            continue

        # --------------------------------------------------------------
        # IN PROGRESS
        # --------------------------------------------------------------

        in_progress_count += 1

    # ------------------------------------------------------------------
    # Recovery rate
    # ------------------------------------------------------------------

    recovery_rate_pct = (
    round(
        (
            amount_recovered
            / historical_amount_at_risk
        )
        * 100,
        1,
    )
    if historical_amount_at_risk
    else 0.0
)

    # ------------------------------------------------------------------
    # Failure category metrics
    # ------------------------------------------------------------------

    failure_categories = _fetchall(
        """
        SELECT
            failure_category,
            COUNT(*) AS total,
            SUM(
                CASE
                    WHEN status = 'paid'
                    THEN 1
                    ELSE 0
                END
            ) AS recovered
        FROM invoices
        WHERE batch_id = ?
        GROUP BY failure_category
        ORDER BY failure_category
        """,
        (batch_id,),
    )

    # ------------------------------------------------------------------
    # Action metrics
    # ------------------------------------------------------------------

    action_metrics = _fetchall(
        """
        SELECT
            action_type,
            COUNT(*) AS actions,
            SUM(
                CASE
                    WHEN status = 'executed'
                    THEN 1
                    ELSE 0
                END
            ) AS executed,
            SUM(
                CASE
                    WHEN status = 'blocked'
                    THEN 1
                    ELSE 0
                END
            ) AS blocked
        FROM recovery_actions
        WHERE batch_id = ?
        GROUP BY action_type
        ORDER BY action_type
        """,
        (batch_id,),
    )

    # ------------------------------------------------------------------
    # Subscription status metrics
    # ------------------------------------------------------------------

    subscription_status = _fetchall(
        """
        SELECT
            status,
            COUNT(*) AS count
        FROM subscriptions
        WHERE batch_id = ?
        GROUP BY status
        ORDER BY status
        """,
        (batch_id,),
    )

    # ------------------------------------------------------------------
    # Average recovery attempts
    # ------------------------------------------------------------------

    average_recovery_attempts_row = _fetchone(
        """
        SELECT
            AVG(
                (
                    SELECT COUNT(*)
                    FROM payment_attempts pa
                    WHERE pa.invoice_id = i.invoice_id
                      AND pa.attempt_type IN (
                          'auto_retry',
                          'manual_retry',
                          'recovery_payment'
                      )
                )
            ) AS avg_attempts
        FROM invoices i
        WHERE i.batch_id = ?
          AND i.invoice_id IN (
              SELECT DISTINCT invoice_id
              FROM revenue_events
              WHERE batch_id = ?
                AND event_type = 'recovery_confirmed'
          )
        """,
        (batch_id, batch_id),
    )

    average_recovery_attempts = round(
        float(
            average_recovery_attempts_row[
                "avg_attempts"
            ]
            or 0
        ),
        2,
    )

    # ------------------------------------------------------------------
    # Guardrail metrics
    # ------------------------------------------------------------------

    guardrail_row = _fetchone(
        """
        SELECT COUNT(*) AS count
        FROM recovery_actions
        WHERE batch_id = ?
          AND status = 'blocked'
        """,
        (batch_id,),
    )

    guardrail_blocks = int(
        guardrail_row["count"] or 0
    )

    # ------------------------------------------------------------------
    # Consistency check
    # ------------------------------------------------------------------

    classified_total = (
        recovered_count
        + in_progress_count
        + exhausted_count
        + blocked_count
        + manual_review_count
    )

    return {
        "batch_id": batch_id,
        "exists": True,

        # --------------------------------------------------------------
        # Financial metrics
        # --------------------------------------------------------------

        "historical_invoices_at_risk": historical_invoices_at_risk,
        "historical_amount_at_risk": historical_amount_at_risk,

        "recovered_count": recovered_count,
        "amount_recovered": amount_recovered,

        "recovery_rate_pct": recovery_rate_pct,

        # --------------------------------------------------------------
        # Outcome metrics
        # --------------------------------------------------------------

        "in_progress_count": in_progress_count,
        "exhausted_count": exhausted_count,
        "blocked_count": blocked_count,
        "manual_review_count": manual_review_count,

        # --------------------------------------------------------------
        # Integrity
        # --------------------------------------------------------------

        "outcome_count_total": classified_total,
        "outcome_count_matches_invoice_count": (
            classified_total == len(invoices)
        ),

        # --------------------------------------------------------------
        # Supporting metrics
        # --------------------------------------------------------------

        "average_recovery_attempts": (
            average_recovery_attempts
        ),

        "guardrail_blocks": guardrail_blocks,

        "failure_categories": [
            dict(row)
            for row in failure_categories
        ],

        "action_metrics": [
            dict(row)
            for row in action_metrics
        ],

        "subscription_status": [
            dict(row)
            for row in subscription_status
        ],
    }


# ===========================================================================
# Recovery timeline
# ===========================================================================

def get_recovery_timeline(
    *,
    subscription_id: str | None = None,
    invoice_id: str | None = None,
) -> list[dict]:
    """
    Return a unified timeline useful for the audit UI.

    The timeline combines:
      - audit entries
      - payment attempts
      - revenue events

    This is intentionally read-only and does not mutate state.
    """
    events: list[dict] = []

    if subscription_id:
        audits = get_audit_log(subscription_id=subscription_id)
        attempts = get_payment_attempts(subscription_id=subscription_id)
        revenues = _fetchall(
            """
            SELECT *
            FROM revenue_events
            WHERE subscription_id = ?
            ORDER BY event_timestamp ASC, event_id ASC
            """,
            (subscription_id,),
        )
    elif invoice_id:
        audits = get_audit_log(invoice_id=invoice_id)
        attempts = get_payment_attempts(invoice_id=invoice_id)
        revenues = get_revenue_events(invoice_id=invoice_id)
    else:
        return []

    for row in audits:
        events.append(
            {
                "timestamp": row["timestamp"],
                "type": "audit",
                "stage": row["stage"],
                "result": row["result"],
                "detail": row["detail"],
                "source_id": row["log_id"],
            }
        )

    for row in attempts:
        events.append(
            {
                "timestamp": row["executed_at"] or row["created_at"],
                "type": "payment_attempt",
                "stage": "execute",
                "result": row["result"],
                "detail": row["result_detail"],
                "source_id": row["attempt_id"],
            }
        )

    for row in revenues:
        events.append(
            {
                "timestamp": row["event_timestamp"],
                "type": "revenue_event",
                "stage": "revenue",
                "result": row["event_type"],
                "detail": row["detail"],
                "source_id": row["event_id"],
            }
        )

    events.sort(
        key=lambda item: (
            item["timestamp"] or "",
            item["type"],
            item["source_id"],
        )
    )

    return events


# ===========================================================================
# Reset helpers
# ===========================================================================

def clear_all_data() -> None:
    """
    Delete application data while preserving the schema.

    Intended for controlled local/demo resets.
    """
    with get_conn() as conn:
        conn.execute("DELETE FROM audit_log")
        conn.execute("DELETE FROM revenue_events")
        conn.execute("DELETE FROM recovery_actions")
        conn.execute("DELETE FROM payment_attempts")
        conn.execute("DELETE FROM invoices")
        conn.execute("DELETE FROM subscriptions")
        conn.execute("DELETE FROM batch_runs")


# ===========================================================================
# Backward-compatible aliases during migration
# ===========================================================================

def get_failed_payments(status: str | None = None) -> list[dict]:
    """
    Temporary compatibility helper.

    Older modules currently expect a payment-centric function. Until those
    modules are migrated, return invoices joined to their subscription data.

    This should eventually be removed once detection.py and the remaining
    modules are converted to the subscription/invoice model.
    """
    conditions: list[str] = []
    params: list[Any] = []

    if status is not None:
        conditions.append("i.status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    return _fetchall(
        f"""
        SELECT
            i.invoice_id AS payment_id,
            i.subscription_id,
            i.batch_id,
            s.customer_id,
            s.customer_name,
            s.customer_email,
            i.amount,
            i.currency,
            NULL AS raw_error_code,
            i.failure_category,
            i.status,
            s.retry_count AS retry_count,
            NULL AS last_attempt_at,
            i.created_at,
            i.updated_at
        FROM invoices i
        JOIN subscriptions s
          ON s.subscription_id = i.subscription_id
        {where}
        ORDER BY i.created_at DESC
        """,
        tuple(params),
    )


def get_payment(payment_id: str) -> dict | None:
    """
    Temporary compatibility wrapper.

    Old modules refer to a 'payment'; during migration this resolves the
    corresponding invoice/subscription representation.
    """
    return _fetchone(
        """
        SELECT
            i.invoice_id AS payment_id,
            i.subscription_id,
            i.batch_id,
            s.customer_id,
            s.customer_name,
            s.customer_email,
            i.amount,
            i.currency,
            NULL AS raw_error_code,
            i.failure_category,
            i.status,
            s.retry_count AS retry_count,
            NULL AS last_attempt_at,
            i.created_at,
            i.updated_at
        FROM invoices i
        JOIN subscriptions s
          ON s.subscription_id = i.subscription_id
        WHERE i.invoice_id = ?
        """,
        (payment_id,),
    )


def update_payment_status(
    payment_id: str,
    status: str,
    retry_count: int | None = None,
) -> None:
    """
    Temporary compatibility wrapper.

    Old execution code can continue to update the invoice status while the
    execution module is being migrated.
    """
    update_invoice_status(payment_id, status)

    payment = get_payment(payment_id)

    if payment and retry_count is not None:
        update_subscription_status(
            payment["subscription_id"],
            payment["status"],
            retry_count=retry_count,
        )