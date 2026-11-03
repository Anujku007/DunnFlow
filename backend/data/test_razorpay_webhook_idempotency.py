from backend.webhooks import handler as webhook_handler
from threading import Barrier, Lock
from concurrent.futures import ThreadPoolExecutor
import pytest

from backend.data import db
from datetime import datetime, timezone

from backend.data.db import (
    create_batch_run,
    create_payment_attempt,
    upsert_invoice,
    upsert_subscription,
)
from backend.integrations.razorpay_adapter import RazorpayAdapter
from backend.integrations.razorpay_ingestion import RazorpayIngestion
from backend.webhooks.handler import handle_razorpay_webhook


@pytest.fixture
def isolated_webhook_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "webhook_test.db")
    db.init_db()


def test_duplicate_webhook_event_is_not_ingested_twice(
    isolated_webhook_db, monkeypatch
):
    ingestion_calls = []

    monkeypatch.setattr(
        RazorpayAdapter,
        "normalize_payment",
        lambda self, entity: {
            "status": "failed",
            "razorpay_payment_id": "pay_test_duplicate",
            "razorpay_order_id": None,
            "amount": 29900,
            "currency": "INR",
        },
    )

    def fake_ingest(self, payment):
        ingestion_calls.append(payment)
        return {"status": "test_ingested"}

    monkeypatch.setattr(
        RazorpayIngestion, "ingest_payment", fake_ingest
    )

    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_duplicate",
                    "status": "failed",
                    "amount": 29900,
                    "currency": "INR",
                }
            }
        },
    }
    event_id = "evt_test_duplicate_delivery"

    first = handle_razorpay_webhook(payload, event_id=event_id)
    second = handle_razorpay_webhook(payload, event_id=event_id)

    assert first["status"] == "processed"
    assert second["status"] == "duplicate"
    assert len(ingestion_calls) == 1

    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT event_id FROM razorpay_webhook_events WHERE event_id = ?",
            (event_id,),
        ).fetchall()

    assert len(rows) == 1

def test_captured_payment_is_idempotent_across_webhook_deliveries(
    isolated_webhook_db, monkeypatch
):
    batch_id = "webhook_captured_test_batch"
    subscription_id = "webhook_captured_test_sub"
    invoice_id = "webhook_captured_test_invoice"
    order_id = "order_test_captured_299"
    payment_id = "pay_test_captured_299"
    amount = 29900
    now = datetime.now(timezone.utc).isoformat()

    create_batch_run(batch_id, started_at=now, status="running")

    upsert_subscription({
        "subscription_id": subscription_id,
        "batch_id": batch_id,
        "customer_id": "webhook_captured_test_customer",
        "amount": amount,
        "currency": "INR",
        "status": "pending",
        "current_cycle": 1,
        "retry_count": 0,
        "created_at": now,
        "updated_at": now,
    })

    upsert_invoice({
        "invoice_id": invoice_id,
        "batch_id": batch_id,
        "subscription_id": subscription_id,
        "amount": amount,
        "currency": "INR",
        "status": "issued",
        "issued_at": now,
        "created_at": now,
        "updated_at": now,
    })

    with db.get_conn() as conn:
        conn.execute(
            "UPDATE invoices SET razorpay_order_id = ? WHERE invoice_id = ?",
            (order_id, invoice_id),
        )

    attempt_id = create_payment_attempt({
        "batch_id": batch_id,
        "invoice_id": invoice_id,
        "subscription_id": subscription_id,
        "razorpay_payment_id": None,
        "attempt_number": 2,
        "attempt_type": "external_razorpay",
        "action_type": None,
        "scheduled_for": None,
        "executed_at": None,
        "result": "pending",
        "raw_error_code": None,
        "failure_reason": None,
        "gateway_status": "pending",
        "result_detail": "Synthetic webhook idempotency test",
        "created_at": now,
    })

    monkeypatch.setattr(
        RazorpayAdapter,
        "normalize_payment",
        lambda self, entity: {
            "status": "captured",
            "razorpay_payment_id": payment_id,
            "razorpay_order_id": order_id,
            "amount": amount,
            "currency": "INR",
            "created": int(datetime.now(timezone.utc).timestamp()),
        },
    )

    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "status": "captured",
                    "amount": amount,
                    "currency": "INR",
                }
            }
        },
    }

    first = handle_razorpay_webhook(
        payload, event_id="evt_captured_test_delivery_1"
    )
    replay = handle_razorpay_webhook(
        payload, event_id="evt_captured_test_delivery_1"
    )
    second_event = handle_razorpay_webhook(
        payload, event_id="evt_captured_test_delivery_2"
    )

    assert first["status"] == "processed"
    assert replay["status"] == "duplicate"
    assert second_event["status"] == "processed"

    with db.get_conn() as conn:
        invoice = conn.execute(
            "SELECT status FROM invoices WHERE invoice_id = ?",
            (invoice_id,),
        ).fetchone()
        subscription = conn.execute(
            "SELECT status FROM subscriptions WHERE subscription_id = ?",
            (subscription_id,),
        ).fetchone()
        attempts = conn.execute(
            """
            SELECT attempt_id, result, gateway_status, razorpay_payment_id
            FROM payment_attempts WHERE invoice_id = ?
            """,
            (invoice_id,),
        ).fetchall()
        recovery_events = conn.execute(
            """
            SELECT amount, razorpay_event_id FROM revenue_events
            WHERE invoice_id = ? AND event_type = 'recovery_confirmed'
            """,
            (invoice_id,),
        ).fetchall()
        webhook_events = conn.execute(
            """
            SELECT event_id FROM razorpay_webhook_events
            WHERE event_id IN (?, ?)
            """,
            ("evt_captured_test_delivery_1", "evt_captured_test_delivery_2"),
        ).fetchall()

    assert invoice["status"] == "paid"
    assert subscription["status"] == "active"
    assert len(attempts) == 1
    assert attempts[0]["attempt_id"] == attempt_id
    assert attempts[0]["result"] == "succeeded"
    assert attempts[0]["gateway_status"] == "captured"
    assert attempts[0]["razorpay_payment_id"] == payment_id

    assert len(recovery_events) == 1
    assert recovery_events[0]["amount"] == amount
    assert recovery_events[0]["razorpay_event_id"] == payment_id
    assert len(webhook_events) == 2

    metrics = db.get_batch_metrics(batch_id)
    assert metrics["recovered_count"] == 1
    assert metrics["amount_recovered"] == amount


def test_concurrent_duplicate_webhook_is_ingested_once(
    isolated_webhook_db, monkeypatch
):
    event_id = "evt_concurrent_duplicate_test"
    payment_id = "pay_concurrent_duplicate_test"
    order_id = "order_concurrent_duplicate_test"

    # Force both deliveries to finish the duplicate check together.
    duplicate_check_barrier = Barrier(2)
    ingestion_lock = Lock()
    ingestion_calls = []

    def both_deliveries_see_unrecorded_event(received_event_id):
        assert received_event_id == event_id
        duplicate_check_barrier.wait(timeout=10)
        return False

    def normalize_failed_payment(self, entity):
        return {
            "status": "failed",
            "razorpay_payment_id": payment_id,
            "razorpay_order_id": order_id,
            "amount": 29900,
            "currency": "INR",
            "created": 0,
        }

    def record_ingestion(self, payment, *, batch_id="benchmark_60_subscription_failures"):
        with ingestion_lock:
            ingestion_calls.append(payment.copy())
        return {"status": "ingested"}

    monkeypatch.setattr(
        webhook_handler,
        "webhook_event_exists",
        both_deliveries_see_unrecorded_event,
    )
    monkeypatch.setattr(
        RazorpayAdapter,
        "normalize_payment",
        normalize_failed_payment,
    )
    monkeypatch.setattr(
        RazorpayIngestion,
        "ingest_payment",
        record_ingestion,
    )

    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "status": "failed",
                    "amount": 29900,
                    "currency": "INR",
                }
            }
        },
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                handle_razorpay_webhook,
                payload,
                event_id=event_id,
            )
            for _ in range(2)
        ]
        results = [future.result(timeout=15) for future in futures]

    assert sorted(result["status"] for result in results) == [
        "duplicate",
        "processed",
    ]

    # This must remain one even when both deliveries overlap.
    assert len(ingestion_calls) == 1

    with db.get_conn() as conn:
        stored_events = conn.execute(
            "SELECT COUNT(*) FROM razorpay_webhook_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()[0]

    assert stored_events == 1

def test_webhook_claim_is_released_after_ingestion_exception(
    isolated_webhook_db, monkeypatch
):
    event_id = "evt_retry_after_exception_test"
    payment_id = "pay_retry_after_exception_test"
    order_id = "order_retry_after_exception_test"
    calls = []

    def normalize_failed_payment(self, entity):
        return {
            "status": "failed",
            "razorpay_payment_id": payment_id,
            "razorpay_order_id": order_id,
            "amount": 29900,
            "currency": "INR",
            "created": 0,
        }

    def fail_once_then_succeed(self, payment, *, batch_id="benchmark_60_subscription_failures"):
        calls.append(payment.copy())
        if len(calls) == 1:
            raise RuntimeError("Synthetic ingestion failure")
        return {"status": "ingested"}

    monkeypatch.setattr(
        RazorpayAdapter, "normalize_payment", normalize_failed_payment
    )
    monkeypatch.setattr(
        RazorpayIngestion, "ingest_payment", fail_once_then_succeed
    )

    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "status": "failed",
                    "amount": 29900,
                    "currency": "INR",
                }
            }
        },
    }

    assert not db.webhook_event_exists(event_id)

    with pytest.raises(RuntimeError, match="Synthetic ingestion failure"):
        handle_razorpay_webhook(payload, event_id=event_id)

    # A failed processing attempt must not permanently block a retry.
    assert not db.webhook_event_exists(event_id)

    retry = handle_razorpay_webhook(payload, event_id=event_id)

    assert retry["status"] == "processed"
    assert len(calls) == 2
    assert db.webhook_event_exists(event_id)
