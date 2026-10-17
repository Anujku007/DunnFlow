"""Create visitor-isolated synthetic benchmark runs without resetting shared data."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from backend.data.db import (
    get_conn,
    init_db,
    create_batch_run,
    create_payment_attempt,
    record_revenue_event,
    update_batch_run,
    upsert_invoice,
    upsert_subscription,
)
from backend.data.seed_data import (
    BENCHMARK_SIZE,
    SCENARIO_SEQUENCE,
    INSUFFICIENT_EXHAUST_CASES,
    INSUFFICIENT_GUARDRAIL_CASES,
    build_subscription,
    build_invoice,
    build_initial_failed_attempt,
    seed_previous_retries,
    record_initial_revenue_events,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_demo_runs_table() -> None:
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS demo_runs (
                run_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


def get_demo_run(run_id: str) -> dict | None:
    _ensure_demo_runs_table()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT run_id, batch_id, status, created_at "
            "FROM demo_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return dict(row) if row else None


def create_isolated_demo_run() -> dict:
    """
    Create 60 fresh synthetic cases with unique IDs.
    Never clears, overwrites, or executes the reference benchmark.
    """
    init_db()
    _ensure_demo_runs_table()

    token = uuid4().hex + uuid4().hex
    prefix = uuid4().hex[:12]
    batch_id = f"demo_{prefix}"
    created_at = _now_iso()

    # Register ownership first; all records below belong to this unique batch.
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO demo_runs (run_id, batch_id, status, created_at) "
            "VALUES (?, ?, ?, ?)",
            (token, batch_id, "creating", created_at),
        )

    try:
        create_batch_run(batch_id, started_at=created_at, status="running")

        total_amount = 0
        for index in range(BENCHMARK_SIZE):
            number = index + 1
            scenario = SCENARIO_SEQUENCE[index]

            if number in INSUFFICIENT_EXHAUST_CASES:
                retry_count = 2
            elif number in INSUFFICIENT_GUARDRAIL_CASES:
                retry_count = 1
            else:
                retry_count = 0

            subscription = build_subscription(
                index=index,
                batch_id=batch_id,
                created_at=created_at,
                scenario=scenario,
                initial_retry_count=retry_count,
            )
            subscription["subscription_id"] = (
                f"sub_demo_{prefix}_{number:03d}"
            )
            subscription["razorpay_subscription_id"] = (
                f"sub_test_demo_{prefix}_{number:03d}"
            )
            subscription["customer_id"] = (
                f"cust_demo_{prefix}_{number:03d}"
            )
            upsert_subscription(subscription)

            invoice = build_invoice(
                index=index,
                batch_id=batch_id,
                subscription=subscription,
                created_at=created_at,
                scenario=scenario,
            )
            invoice["invoice_id"] = f"inv_demo_{prefix}_{number:03d}"
            invoice["razorpay_invoice_id"] = (
                f"inv_test_demo_{prefix}_{number:03d}"
            )
            invoice["subscription_id"] = subscription["subscription_id"]
            upsert_invoice(invoice)

            attempt = build_initial_failed_attempt(
                index=index,
                batch_id=batch_id,
                subscription=subscription,
                invoice=invoice,
                created_at=created_at,
                scenario=scenario,
            )
            attempt["razorpay_payment_id"] = (
                f"pay_test_demo_{prefix}_{number:03d}_01"
            )
            attempt_id = create_payment_attempt(attempt)

            # Preserve the benchmark's intentional exhaustion/guardrail history.
            seed_previous_retries(
                index=index,
                batch_id=batch_id,
                subscription=subscription,
                invoice=invoice,
                scenario=scenario,
            )

            record_initial_revenue_events(
                batch_id=batch_id,
                subscription=subscription,
                invoice=invoice,
                payment_attempt_id=attempt_id,
                created_at=created_at,
                scenario=scenario,
            )
            total_amount += int(invoice["amount"])

        update_batch_run(
            batch_id,
            status="running",
            total_subscriptions=BENCHMARK_SIZE,
            total_invoices=BENCHMARK_SIZE,
            amount_at_risk=total_amount,
            amount_recovered=0,
            recovered_count=0,
            exhausted_count=0,
            in_progress_count=0,
            manual_review_count=0,
        )

        with get_conn() as conn:
            conn.execute(
                "UPDATE demo_runs SET status = 'ready' WHERE run_id = ?",
                (token,),
            )

        # Keep the four scenario cards aligned with the reference case numbers.
        return {
            "run_id": token,
            "batch_id": batch_id,
            "mode": "synthetic_test_mode",
            "case_count": BENCHMARK_SIZE,
            "scenario_cards": {
                "fresh": f"inv_demo_{prefix}_006",
                "guardrail": f"inv_demo_{prefix}_012",
                "manual_review": f"inv_demo_{prefix}_060",
                "successful_recovery": f"inv_demo_{prefix}_030",
            },
        }
    except Exception:
        with get_conn() as conn:
            conn.execute(
                "UPDATE demo_runs SET status = 'failed' WHERE run_id = ?",
                (token,),
            )
        raise
