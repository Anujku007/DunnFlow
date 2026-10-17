import pytest

from backend.data import db
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
