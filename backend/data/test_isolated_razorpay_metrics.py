import pytest

from backend.data import db


@pytest.fixture
def isolated_demo_metrics_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "isolated_demo_metrics.db")
    db.init_db()

    from backend.data.razorpay_demo import ensure_razorpay_demo_sessions_table
    ensure_razorpay_demo_sessions_table()

    now = "2026-10-16T00:00:00+00:00"

    with db.get_conn() as conn:
        for index, paid in ((1, True), (2, False)):
            batch_id = f"rp_demo_metrics_batch_{index}"
            sub_id = f"rp_demo_metrics_sub_{index}"
            invoice_id = f"rp_demo_metrics_invoice_{index}"
            status = "paid" if paid else "issued"

            conn.execute(
                """
                INSERT INTO batch_runs (batch_id, started_at, status)
                VALUES (?, ?, 'running')
                """,
                (batch_id, now),
            )
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, batch_id, customer_id, amount,
                    currency, status, created_at, updated_at
                )
                VALUES (?, ?, ?, 29900, 'INR', ?, ?, ?)
                """,
                (
                    sub_id, batch_id, f"customer_{index}",
                    "active" if paid else "pending", now, now,
                ),
            )
            conn.execute(
                """
                INSERT INTO invoices (
                    invoice_id, batch_id, subscription_id, amount,
                    currency, status, issued_at, paid_at,
                    created_at, updated_at, failure_category
                )
                VALUES (?, ?, ?, 29900, 'INR', ?, ?, ?, ?, ?, 'card_expired')
                """,
                (
                    invoice_id, batch_id, sub_id, status, now,
                    now if paid else None, now, now,
                ),
            )
            conn.execute(
                """
                INSERT INTO razorpay_demo_sessions (
                    session_id, idempotency_key, batch_id, invoice_id,
                    subscription_id, razorpay_order_id, status,
                    amount_paise, currency, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 29900, 'INR', ?, ?)
                """,
                (
                    f"rp_demo_session_{index}", f"metrics-key-{index}",
                    batch_id, invoice_id, sub_id, f"order_test_{index}",
                    "paid" if paid else "order_created", now, now,
                ),
            )
            conn.execute(
                """
                INSERT INTO revenue_events (
                    batch_id, subscription_id, invoice_id,
                    event_type, amount, razorpay_event_id,
                    event_timestamp, detail
                )
                VALUES (?, ?, ?, 'revenue_at_risk', 29900, NULL, ?, ?)
                """,
                (batch_id, sub_id, invoice_id, now, "Test risk event"),
            )

            if paid:
                conn.execute(
                    """
                    INSERT INTO revenue_events (
                        batch_id, subscription_id, invoice_id,
                        event_type, amount, razorpay_event_id,
                        event_timestamp, detail
                    )
                    VALUES (?, ?, ?, 'recovery_confirmed', 29900, ?, ?, ?)
                    """,
                    (
                        batch_id, sub_id, invoice_id,
                        f"pay_test_{index}", now, "Test confirmed recovery",
                    ),
                )

    return True


def test_isolated_demo_metrics_expected_aggregate(isolated_demo_metrics_db):
    # This assertion is intentionally against the future aggregate function.
    # It should fail until that function is implemented.
    from backend.data.razorpay_demo import get_isolated_razorpay_demo_metrics

    metrics = get_isolated_razorpay_demo_metrics()

    assert metrics["recovery_count"] == 2
    assert metrics["recovered_count"] == 1
    assert metrics["amount_recovered"] == 29900
    assert metrics["amount_at_risk"] == 29900
    assert metrics["in_progress_count"] == 1
    assert metrics["recovery_rate_pct"] == 50.0
