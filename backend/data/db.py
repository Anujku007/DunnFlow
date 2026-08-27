"""
Data access layer for DunnFlow.

Every other module talks to the DB only through these functions —
never raw SQL scattered elsewhere. This is what lets us swap
SQLite -> Postgres/Mongo later without touching business logic.
"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parents[2] / "dunnflow.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist. Safe to call every startup."""
    with get_conn() as conn:
        conn.executescript(SCHEMA_PATH.read_text())


# ---------- payments ----------

def upsert_payment(payment: dict):
    """Insert a new failed payment, or update it if it already exists."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO payments (
                payment_id, customer_id, customer_name, customer_email,
                amount, currency, raw_error_code, failure_reason,
                failure_category, status, retry_count, last_attempt_at,
                created_at, updated_at
            ) VALUES (:payment_id, :customer_id, :customer_name, :customer_email,
                      :amount, :currency, :raw_error_code, :failure_reason,
                      :failure_category, :status, :retry_count, :last_attempt_at,
                      :created_at, :updated_at)
            ON CONFLICT(payment_id) DO UPDATE SET
                failure_category = excluded.failure_category,
                status = excluded.status,
                retry_count = excluded.retry_count,
                last_attempt_at = excluded.last_attempt_at,
                updated_at = excluded.updated_at
            """,
            {
                "payment_id": payment["payment_id"],
                "customer_id": payment["customer_id"],
                "customer_name": payment.get("customer_name"),
                "customer_email": payment.get("customer_email"),
                "amount": payment["amount"],
                "currency": payment.get("currency", "INR"),
                "raw_error_code": payment.get("raw_error_code"),
                "failure_reason": payment.get("failure_reason"),
                "failure_category": payment.get("failure_category"),
                "status": payment.get("status", "failed"),
                "retry_count": payment.get("retry_count", 0),
                "last_attempt_at": payment.get("last_attempt_at"),
                "created_at": payment.get("created_at", _now()),
                "updated_at": _now(),
            },
        )


def get_payment(payment_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM payments WHERE payment_id = ?", (payment_id,)
        ).fetchone()
        return dict(row) if row else None


def get_failed_payments(status: str | None = None) -> list[dict]:
    """Fetch payments, optionally filtered by status (failed/recovered/exhausted/pending_retry)."""
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM payments WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM payments ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def update_payment_status(payment_id: str, status: str, retry_count: int | None = None):
    with get_conn() as conn:
        if retry_count is not None:
            conn.execute(
                "UPDATE payments SET status = ?, retry_count = ?, last_attempt_at = ?, updated_at = ? WHERE payment_id = ?",
                (status, retry_count, _now(), _now(), payment_id),
            )
        else:
            conn.execute(
                "UPDATE payments SET status = ?, updated_at = ? WHERE payment_id = ?",
                (status, _now(), payment_id),
            )


# ---------- retry_attempts ----------

def log_retry_attempt(attempt: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO retry_attempts (
                payment_id, attempt_number, action_type, scheduled_for,
                executed_at, result, result_detail
            ) VALUES (:payment_id, :attempt_number, :action_type, :scheduled_for,
                      :executed_at, :result, :result_detail)
            """,
            attempt,
        )
        return cur.lastrowid


def get_retry_attempts(payment_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM retry_attempts WHERE payment_id = ? ORDER BY attempt_number",
            (payment_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def count_attempts_last_n_hours(payment_id: str, hours: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c FROM retry_attempts
            WHERE payment_id = ?
              AND executed_at >= datetime('now', ?)
            """,
            (payment_id, f"-{hours} hours"),
        ).fetchone()
        return row["c"] if row else 0


# ---------- audit_log ----------

def log_audit_entry(entry: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO audit_log (
                payment_id, customer_id, stage, failure_category,
                action_taken, guardrail_hit, result, detail, timestamp
            ) VALUES (:payment_id, :customer_id, :stage, :failure_category,
                      :action_taken, :guardrail_hit, :result, :detail, :timestamp)
            """,
            {**entry, "timestamp": entry.get("timestamp", _now())},
        )
        return cur.lastrowid


def get_audit_log(payment_id: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if payment_id:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE payment_id = ? ORDER BY timestamp",
                (payment_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY timestamp DESC"
            ).fetchall()
        return [dict(r) for r in rows]


# ---------- metrics ----------

def get_metrics_summary() -> dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) c, COALESCE(SUM(amount),0) a FROM payments").fetchone()
        recovered = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(amount),0) a FROM payments WHERE status = 'recovered'"
        ).fetchone()
        exhausted = conn.execute(
            "SELECT COUNT(*) c FROM payments WHERE status = 'exhausted'"
        ).fetchone()
        by_category = conn.execute(
            """
            SELECT failure_category,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status = 'recovered' THEN 1 ELSE 0 END) AS recovered
            FROM payments
            GROUP BY failure_category
            """
        ).fetchall()

        return {
            "total_failed_payments": total["c"],
            "total_amount_at_risk": total["a"],
            "recovered_count": recovered["c"],
            "recovered_amount": recovered["a"],
            "exhausted_count": exhausted["c"],
            "recovery_rate_pct": round((recovered["c"] / total["c"]) * 100, 1) if total["c"] else 0.0,
            "by_category": [dict(r) for r in by_category],
        }