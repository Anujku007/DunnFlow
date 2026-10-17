import pytest

from backend.data import db


@pytest.fixture
def fresh_unpaid_invoice(tmp_path, monkeypatch):
    """Build a fresh ₹299 invoice in a temporary database."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "fresh_session_test.db")
    db.init_db()

    batch_id = "rp_demo_regression_batch"
    subscription_id = "rp_demo_regression_sub"
    invoice_id = "rp_demo_regression_invoice"
    now = "2026-10-16T00:00:00+00:00"
    amount = 29900

    with db.get_conn() as conn:
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
            VALUES (?, ?, ?, ?, 'INR', 'pending', ?, ?)
            """,
            (subscription_id, batch_id, "regression_customer", amount, now, now),
        )
        conn.execute(
            """
            INSERT INTO invoices (
                invoice_id, batch_id, subscription_id, amount,
                currency, status, issued_at, paid_at,
                created_at, updated_at, failure_category
            )
            VALUES (?, ?, ?, ?, 'INR', 'issued', ?, NULL, ?, ?, 'card_expired')
            """,
            (invoice_id, batch_id, subscription_id, amount, now, now, now),
        )
        conn.execute(
            """
            INSERT INTO revenue_events (
                batch_id, subscription_id, invoice_id,
                event_type, amount, event_timestamp, detail
            )
            VALUES (?, ?, ?, 'revenue_at_risk', ?, ?, ?)
            """,
            (batch_id, subscription_id, invoice_id, amount, now, "Fresh invoice risk"),
        )
        conn.execute(
            """
            INSERT INTO payment_attempts (
                batch_id, invoice_id, subscription_id,
                attempt_number, attempt_type, result,
                raw_error_code, failure_reason, created_at
            )
            VALUES (?, ?, ?, 1, 'initial_charge', 'failed',
                    'card_expired', 'Synthetic test failure', ?)
            """,
            (batch_id, invoice_id, subscription_id, now),
        )

    return batch_id


def test_fresh_unpaid_session_metrics(fresh_unpaid_invoice):
    metrics = db.get_batch_metrics(fresh_unpaid_invoice)

    assert metrics["exists"] is True
    assert metrics["amount_at_risk"] == 29900
    assert metrics["in_progress_count"] == 1
    assert metrics["recovered_count"] == 0
    assert metrics["amount_recovered"] == 0
    assert metrics["recovery_rate_pct"] == 0.0
