import pytest
from fastapi.testclient import TestClient

from backend.data import db
from backend.integrations import razorpay_client
from backend.api import app


class MockRazorpayClientError(Exception):
    pass


class MockRazorpayClient:
    """Test-only gateway. It can never make a network request."""

    configured = True
    key_id = "rzp_test_mock_only"

    def get_mode(self):
        return "test"

    def create_order(self, *, amount, currency, receipt, notes):
        # Prove the invoice was persisted before the gateway boundary.
        metrics = db.get_batch_metrics(
            notes["dunnflow_demo_session_id"]
        ) if False else None

        invoice_id = receipt
        invoice = db.get_invoice(invoice_id)
        assert invoice is not None
        assert invoice["status"] == "issued"
        assert int(invoice["amount"]) == 29900
        assert invoice.get("paid_at") is None

        metrics = db.get_batch_metrics(invoice["batch_id"])
        assert metrics["amount_at_risk"] == 29900
        assert metrics["in_progress_count"] == 1
        assert metrics["recovered_count"] == 0
        assert metrics["amount_recovered"] == 0
        assert metrics["recovery_rate_pct"] == 0.0

        raise MockRazorpayClientError("Mock refuses all order creation")


@pytest.fixture
def isolated_session_api(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "session_endpoint_test.db")
    monkeypatch.setattr(
        razorpay_client, "RazorpayClient", MockRazorpayClient
    )
    monkeypatch.setattr(
        razorpay_client, "RazorpayClientError", MockRazorpayClientError
    )
    db.init_db()
    return TestClient(app)


def test_session_endpoint_persists_unpaid_invoice_without_gateway_order(
    isolated_session_api,
):
    response = isolated_session_api.post(
        "/api/demo/razorpay/session",
        headers={"Idempotency-Key": "isolated-metrics-regression-test"},
    )

    # The fake gateway refuses the request after local initialization.
    assert response.status_code == 502

    # Exactly one fresh session/invoice should exist in the temporary DB.
    with db.get_conn() as conn:
        sessions = conn.execute(
            "SELECT * FROM razorpay_demo_sessions"
        ).fetchall()
        invoices = conn.execute(
            """
            SELECT * FROM invoices
            WHERE batch_id LIKE 'rp_demo_%'
            """
        ).fetchall()

    assert len(sessions) == 1
    assert len(invoices) == 1

    invoice = dict(invoices[0])
    assert invoice["status"] == "issued"
    assert invoice["paid_at"] is None
    assert int(invoice["amount"]) == 29900
    assert invoice["razorpay_order_id"] is None

    metrics = db.get_batch_metrics(invoice["batch_id"])
    assert metrics["amount_at_risk"] == 29900
    assert metrics["in_progress_count"] == 1
    assert metrics["recovered_count"] == 0
    assert metrics["amount_recovered"] == 0
    assert metrics["recovery_rate_pct"] == 0.0
