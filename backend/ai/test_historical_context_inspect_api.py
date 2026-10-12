from fastapi.testclient import TestClient
import unittest
from unittest.mock import patch

from backend.api import app


class HistoricalContextInspectAPITest(unittest.TestCase):
    def test_inspect_endpoint_returns_historical_context_without_live_ai(self):
        historical_context = {
            "historical_evidence_summary": {
                "available": True,
                "sample_size": 11,
                "overall_evidence_quality": "strong",
                "confidence_signal": "high",
                "advisory_only": True,
            },
            "historical_evidence_consistency": {
                "signals": {
                    "failure_category": "historically_unfavorable",
                    "amount_band": "historically_unfavorable",
                    "recency": "recently_unfavorable",
                },
                "consistency_signal": "aligned",
                "interpretation": (
                    "Available historical evidence is directionally aligned; "
                    "this remains advisory context only."
                ),
                "provenance": {
                    "financial_authority": "deterministic_policy",
                },
                "advisory_only": True,
            },
        }

        class MockReconciliation:
            def to_dict(self):
                return {
                    "ai_recommendation": {
                        "available": False,
                        "reason": "AI mocked for isolated test.",
                    },
                    "deterministic_authority": True,
                    "ai_advisory_only": True,
                }

        reconciliation = MockReconciliation()

        with (
            patch("backend.api.get_invoice", return_value={
                "invoice_id": "test_invoice",
                "status": "issued",
            }),
            patch("backend.api.diagnose_invoice", return_value={
                "failure_category": "card_expired",
            }),
            patch("backend.api.decide_for_invoice", return_value={
                "action": "payment_method_update",
            }) as decide,
            patch("backend.api.RecoveryAdvisor") as advisor,
            patch("backend.api.reconcile_invoice",
                  return_value=reconciliation) as reconcile,
            patch("backend.api.get_historical_decision_context_dict",
                  return_value=historical_context) as historical,
        ):
            client = TestClient(app)
            response = client.get(
                "/api/demo/cases/test_invoice/inspect"
            )

        assert response.status_code == 200
        body = response.json()

        assert body["historical_context"]["historical_evidence_summary"][
            "sample_size"
        ] == 11

        consistency = body["historical_context"][
            "historical_evidence_consistency"
        ]
        assert consistency["consistency_signal"] == "aligned"
        assert consistency["signals"]["failure_category"] == (
            "historically_unfavorable"
        )
        assert consistency["advisory_only"] is True
        assert consistency["provenance"]["financial_authority"] == (
            "deterministic_policy"
        )

        assert body["deterministic_authority"] is True
        assert body["ai_advisory_only"] is True
        assert body["read_only"] is True

        advisor.assert_called_once()
        reconcile.assert_called_once()
        historical.assert_called_once_with("test_invoice", limit=20)
        decide.assert_called_once_with("test_invoice", persist=False)


if __name__ == '__main__':
    unittest.main()


