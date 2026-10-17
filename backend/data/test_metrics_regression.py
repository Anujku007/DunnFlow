import sqlite3

import pytest

from backend.data import db


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Use a fresh SQLite database; never touch the project database."""
    test_db = tmp_path / "dunnflow_metrics_test.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_db()

    batch_id = "test_metrics_batch"
    subscription_id = "test_metrics_subscription"
    invoice_id = "test_metrics_invoice"
    now = "2026-01-01T00:00:00+00:00"
    amount = 29900

    with db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO batch_runs (batch_id, started_at, status)
            VALUES (?, ?, 'completed')
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
            (
                subscription_id, batch_id, "test_customer",
                amount, now, now,
            ),
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
            (
                invoice_id, batch_id, subscription_id,
                amount, now, now, now,
            ),
        )
        conn.execute(
            """
            INSERT INTO revenue_events (
                batch_id, subscription_id, invoice_id,
                event_type, amount, event_timestamp, detail
            )
            VALUES (?, ?, ?, 'revenue_at_risk', ?, ?, ?)
            """,
            (
                batch_id, subscription_id, invoice_id,
                amount, now, "Initial risk baseline",
            ),
        )

    return {
        "batch_id": batch_id,
        "subscription_id": subscription_id,
        "invoice_id": invoice_id,
        "amount": amount,
        "now": now,
    }


def test_unpaid_invoice_is_at_risk_and_in_progress(isolated_db):
    metrics = db.get_batch_metrics(isolated_db["batch_id"])

    assert metrics["exists"] is True
    assert metrics["amount_at_risk"] == 29900
    assert metrics["in_progress_count"] == 1
    assert metrics["recovered_count"] == 0
    assert metrics["amount_recovered"] == 0
    assert metrics["recovery_rate_pct"] == 0.0


def test_paid_invoice_moves_from_risk_to_recovered(isolated_db):
    data = isolated_db

    with db.get_conn() as conn:
        conn.execute(
            """
            UPDATE invoices
            SET status = 'paid', paid_at = ?, updated_at = ?
            WHERE invoice_id = ?
            """,
            (data["now"], data["now"], data["invoice_id"]),
        )
        conn.execute(
            """
            UPDATE subscriptions
            SET status = 'active', updated_at = ?
            WHERE subscription_id = ?
            """,
            (data["now"], data["subscription_id"]),
        )
        conn.execute(
            """
            INSERT INTO revenue_events (
                batch_id, subscription_id, invoice_id,
                event_type, amount, razorpay_event_id,
                event_timestamp, detail
            )
            VALUES (?, ?, ?, 'recovery_confirmed', ?, ?, ?, ?)
            """,
            (
                data["batch_id"], data["subscription_id"],
                data["invoice_id"], data["amount"],
                "pay_test_regression_001", data["now"],
                "Confirmed test recovery",
            ),
        )

    metrics = db.get_batch_metrics(data["batch_id"])

    assert metrics["amount_at_risk"] == 0
    assert metrics["in_progress_count"] == 0
    assert metrics["recovered_count"] == 1
    assert metrics["amount_recovered"] == 29900
    assert metrics["recovery_rate_pct"] == 100.0


def test_duplicate_recovery_event_does_not_inflate_amount(isolated_db):
    data = isolated_db

    with db.get_conn() as conn:
        conn.execute(
            """
            UPDATE invoices
            SET status = 'paid', paid_at = ?, updated_at = ?
            WHERE invoice_id = ?
            """,
            (data["now"], data["now"], data["invoice_id"]),
        )

        event = (
            data["batch_id"], data["subscription_id"],
            data["invoice_id"], data["amount"],
            "pay_test_duplicate_001", data["now"],
            "Duplicate-delivery regression case",
        )
        sql = """
            INSERT INTO revenue_events (
                batch_id, subscription_id, invoice_id,
                event_type, amount, razorpay_event_id,
                event_timestamp, detail
            )
            VALUES (?, ?, ?, 'recovery_confirmed', ?, ?, ?, ?)
        """
        conn.execute(sql, event)
        conn.execute(sql, event)

    metrics = db.get_batch_metrics(data["batch_id"])

    assert metrics["recovered_count"] == 1
    assert metrics["amount_recovered"] == 29900
    assert metrics["recovery_rate_pct"] == 100.0


def test_execution_totals_do_not_double_count_duplicate_payment_events(
    isolated_db,
):
    from backend.modules.execution import _refresh_batch_recovery_totals

    data = isolated_db

    with db.get_conn() as conn:
        event = (
            data["batch_id"],
            data["subscription_id"],
            data["invoice_id"],
            data["amount"],
            "pay_test_execution_duplicate_001",
            data["now"],
            "Duplicate execution-total regression case",
        )
        sql = """
            INSERT INTO revenue_events (
                batch_id, subscription_id, invoice_id,
                event_type, amount, razorpay_event_id,
                event_timestamp, detail
            )
            VALUES (?, ?, ?, 'recovery_confirmed', ?, ?, ?, ?)
        """
        conn.execute(sql, event)
        conn.execute(sql, event)

    _refresh_batch_recovery_totals(data["batch_id"])

    with db.get_conn() as conn:
        batch = conn.execute(
            "SELECT * FROM batch_runs WHERE batch_id = ?",
            (data["batch_id"],),
        ).fetchone()

    assert batch is not None
    assert batch["recovered_count"] == 1
    assert batch["amount_recovered"] == data["amount"]
