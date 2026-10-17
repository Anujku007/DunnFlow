"""Isolated Razorpay Test Mode visitor demo sessions."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from backend.data.db import get_conn, init_db


DEMO_AMOUNT_RUPEES = 299
DEMO_AMOUNT_PAISE = DEMO_AMOUNT_RUPEES * 100
DEMO_CURRENCY = "INR"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_razorpay_demo_sessions_table() -> None:
    """Create the isolated session registry without altering existing records."""
    init_db()
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS razorpay_demo_sessions (
                session_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                batch_id TEXT NOT NULL UNIQUE,
                invoice_id TEXT NOT NULL UNIQUE,
                subscription_id TEXT NOT NULL UNIQUE,
                razorpay_order_id TEXT UNIQUE,
                status TEXT NOT NULL,
                amount_paise INTEGER NOT NULL,
                currency TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def get_razorpay_demo_session_by_order_id(
    razorpay_order_id: str,
) -> dict | None:
    """Return the isolated demo session associated with one Razorpay order."""
    if not razorpay_order_id:
        return None

    ensure_razorpay_demo_sessions_table()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM razorpay_demo_sessions
            WHERE razorpay_order_id = ?
            """,
            (razorpay_order_id,),
        ).fetchone()
        return dict(row) if row else None


def get_razorpay_demo_session_by_key(idempotency_key: str) -> dict | None:
    ensure_razorpay_demo_sessions_table()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM razorpay_demo_sessions
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None


def get_razorpay_demo_session(session_id: str) -> dict | None:
    ensure_razorpay_demo_sessions_table()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM razorpay_demo_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None



def get_razorpay_demo_session_by_invoice_id(invoice_id: str) -> dict | None:
    """Return an existing isolated Razorpay session for an invoice, read-only."""
    if not isinstance(invoice_id, str) or not invoice_id.strip():
        return None

    ensure_razorpay_demo_sessions_table()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM razorpay_demo_sessions
            WHERE invoice_id = ?
            """,
            (invoice_id.strip(),),
        ).fetchone()
        return dict(row) if row else None


def register_razorpay_demo_session(idempotency_key: str) -> dict:
    """Atomically register a session; repeated keys return the same session."""
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError("A non-empty idempotency key is required.")

    key = idempotency_key.strip()
    if len(key) > 200:
        raise ValueError("Idempotency key must be at most 200 characters.")

    ensure_razorpay_demo_sessions_table()

    existing = get_razorpay_demo_session_by_key(key)
    if existing:
        return existing

    token = uuid4().hex
    prefix = uuid4().hex[:12]
    now = _now_iso()

    session = {
        "session_id": token,
        "idempotency_key": key,
        "batch_id": f"rp_demo_{prefix}",
        "invoice_id": f"inv_rp_demo_{prefix}",
        "subscription_id": f"sub_rp_demo_{prefix}",
        "razorpay_order_id": None,
        "status": "creating",
        "amount_paise": DEMO_AMOUNT_PAISE,
        "currency": DEMO_CURRENCY,
        "created_at": now,
        "updated_at": now,
    }

    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO razorpay_demo_sessions (
                    session_id, idempotency_key, batch_id, invoice_id,
                    subscription_id, razorpay_order_id, status,
                    amount_paise, currency, created_at, updated_at
                ) VALUES (
                    :session_id, :idempotency_key, :batch_id, :invoice_id,
                    :subscription_id, :razorpay_order_id, :status,
                    :amount_paise, :currency, :created_at, :updated_at
                )
                """,
                session,
            )
    except sqlite3.IntegrityError:
        # A concurrent request may have registered the same idempotency key.
        existing = get_razorpay_demo_session_by_key(key)
        if existing:
            return existing
        raise

    return session


def attach_order_to_razorpay_demo_session(
    session_id: str,
    razorpay_order_id: str,
) -> dict:
    """Attach one order to a session; never replace a different order ID."""
    if not session_id or not razorpay_order_id:
        raise ValueError("Session ID and Razorpay order ID are required.")

    ensure_razorpay_demo_sessions_table()
    now = _now_iso()

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM razorpay_demo_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        if not row:
            raise ValueError("Razorpay demo session was not found.")

        current = dict(row)
        existing_order_id = current.get("razorpay_order_id")

        if existing_order_id and existing_order_id != razorpay_order_id:
            raise ValueError("A different Razorpay order is already attached.")

        if current["status"] not in {"creating", "order_request_started", "order_created"}:
            raise ValueError(
                f"Cannot attach an order to session status '{current['status']}'."
            )

        conn.execute(
            """
            UPDATE razorpay_demo_sessions
            SET razorpay_order_id = ?,
                status = 'order_created',
                updated_at = ?
            WHERE session_id = ?
            """,
            (razorpay_order_id, now, session_id),
        )

    result = get_razorpay_demo_session(session_id)
    if not result:
        raise RuntimeError("Session disappeared after order attachment.")
    return result


def update_razorpay_demo_session_status(
    session_id: str,
    status: str,
) -> dict:
    """Update a session status without changing its identity or order."""
    allowed = {
        "creating",
        "order_request_started",
        "order_created",
        "checkout_open",
        "payment_pending",
        "paid",
        "failed",
        "manual_review",
    }
    if status not in allowed:
        raise ValueError("Unsupported Razorpay demo session status.")

    ensure_razorpay_demo_sessions_table()
    now = _now_iso()

    with get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM razorpay_demo_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        if not row:
            raise ValueError("Razorpay demo session was not found.")

        current_status = row["status"]
        if current_status == "paid" and status != "paid":
            raise ValueError("A paid session cannot be moved to another status.")

        conn.execute(
            """
            UPDATE razorpay_demo_sessions
            SET status = ?, updated_at = ?
            WHERE session_id = ?
            """,
            (status, now, session_id),
        )

    result = get_razorpay_demo_session(session_id)
    if not result:
        raise RuntimeError("Session disappeared after status update.")
    return result

def claim_razorpay_demo_order_creation(session_id: str) -> bool:
    """Atomically allow only one request to start an external order request."""
    ensure_razorpay_demo_sessions_table()
    now = _now_iso()

    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE razorpay_demo_sessions
            SET status = 'order_request_started',
                updated_at = ?
            WHERE session_id = ?
              AND status = 'creating'
              AND razorpay_order_id IS NULL
            """,
            (now, session_id),
        )
        return cursor.rowcount == 1



def get_isolated_razorpay_demo_metrics() -> dict:
    """Aggregate canonical metrics across registered isolated demo sessions.

    This function is read-only apart from ensuring the session registry table
    exists. It does not initiate or modify any payment.
    """
    ensure_razorpay_demo_sessions_table()

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT batch_id, session_id
            FROM razorpay_demo_sessions
            ORDER BY created_at, session_id
            """
        ).fetchall()

    # Each registered session has a unique batch_id by schema constraint.
    from backend.data.db import get_batch_metrics

    totals = {
        "exists": bool(rows),
        "scope": "isolated_razorpay_demo",
        "session_count": len(rows),
        "recovery_count": 0,
        "recovered_count": 0,
        "amount_recovered": 0,
        "amount_at_risk": 0,
        "in_progress_count": 0,
        "recovery_rate_pct": 0.0,
        "currency": DEMO_CURRENCY,
    }

    for row in rows:
        metrics = get_batch_metrics(row["batch_id"])

        for key in (
            "recovery_count",
            "recovered_count",
            "amount_recovered",
            "amount_at_risk",
            "in_progress_count",
        ):
            totals[key] += int(metrics.get(key, 0) or 0)

    if totals["recovery_count"]:
        totals["recovery_rate_pct"] = round(
            totals["recovered_count"] / totals["recovery_count"] * 100,
            1,
        )

    return totals
