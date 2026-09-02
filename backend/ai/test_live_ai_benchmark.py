
from __future__ import annotations

from collections import Counter

from backend.ai.ai_policy_reconciliation import reconcile_invoice
from backend.ai.recovery_advisor import (
    AIRecoveryRecommendation,
    AIUnavailableResult,
    RecoveryAdvisor,
)
from backend.data.db import (
    get_invoices,
    get_batch_metrics,
    get_audit_log,
    init_db,
)
from backend.data.seed_data import seed_benchmark
from backend.modules.decision_engine import decide_for_invoice


BATCH_ID = "benchmark_60_subscription_failures"


def main() -> None:
    print("=" * 72)
    print("DUNNFLOW LIVE AI 60-CASE BENCHMARK")
    print("=" * 72)
    print()
    print("WARNING: This test sends up to 60 REAL requests to OpenRouter.")
    print("AI recommendations are reconciled only.")
    print("NO AI recommendation will be executed.")
    print()

    init_db()

    print("SEEDING CLEAN 60-CASE BENCHMARK...")
    batch_id = seed_benchmark(reset=True, size=60)

    if batch_id != BATCH_ID:
        raise SystemExit(
            f"ERROR: Expected batch {BATCH_ID}, got {batch_id}"
        )

    invoices = get_invoices(batch_id=BATCH_ID)

    if len(invoices) != 60:
        raise SystemExit(
            f"ERROR: Expected 60 invoices, found {len(invoices)}"
        )

    advisor = RecoveryAdvisor()

    if not advisor.available:
        raise SystemExit(
            "ERROR: Real AI provider is not available."
        )

    print()
    print("Provider:", advisor.config.provider)
    print("Model:", advisor.config.model)
    print("Invoices:", len(invoices))
    print()

    results = []
    errors = []

    for index, invoice in enumerate(invoices, start=1):
        invoice_id = invoice["invoice_id"]

        print(
            f"[{index:02d}/60] {invoice_id} "
            f"category={invoice.get('failure_category')}"
        )

        try:
            deterministic_decision = decide_for_invoice(
                invoice_id,
                persist=True,
            )

            reconciliation = reconcile_invoice(
                invoice_id=invoice_id,
                deterministic_decision=deterministic_decision,
                advisor=advisor,
            )

            results.append(reconciliation)

            print(
                f"       AI={reconciliation.ai_action} "
                f"POLICY={reconciliation.deterministic_action} "
                f"RESULT={reconciliation.result}"
            )

        except Exception as exc:
            errors.append(
                {
                    "invoice_id": invoice_id,
                    "type": type(exc).__name__,
                    "error": str(exc),
                }
            )

            print(
                f"       ERROR={type(exc).__name__}: {exc}"
            )

    agreements = sum(
        1 for result in results
        if result.result == "agreement"
    )

    disagreements = sum(
        1 for result in results
        if result.result == "disagreement"
    )

    unavailable = sum(
        1 for result in results
        if result.result == "ai_unavailable"
    )

    ai_available_results = sum(
        1 for result in results
        if result.ai_available
    )

    audit_rows = [
        row
        for row in get_audit_log(batch_id=BATCH_ID)
        if row.get("stage") == "ai_policy_check"
    ]

    metrics = get_batch_metrics(BATCH_ID)

    print()
    print("=" * 72)
    print("LIVE AI BENCHMARK RESULTS")
    print("=" * 72)
    print()
    print("Cases requested:        60")
    print("Cases reconciled:       ", len(results))
    print("AI available:           ", ai_available_results)
    print("AI unavailable:         ", unavailable)
    print("AI/policy agreements:   ", agreements)
    print("AI/policy disagreements:", disagreements)
    print("Unexpected errors:      ", len(errors))
    print("AI policy audit rows:   ", len(audit_rows))
    print()

    print("DETERMINISTIC FINANCIAL METRICS")
    print("-" * 72)
    print("Historical invoices at risk:", metrics["historical_invoices_at_risk"])
    print("Historical amount at risk:  ", metrics["historical_amount_at_risk"])
    print("Recovered count:             ", metrics["recovered_count"])
    print("Amount recovered:            ", metrics["amount_recovered"])
    print("Recovery rate:               ", metrics["recovery_rate_pct"])
    print("In progress:                 ", metrics["in_progress_count"])
    print("Blocked:                     ", metrics["blocked_count"])
    print("Manual review:               ", metrics["manual_review_count"])
    print("Outcome count:               ", metrics["outcome_count_total"])
    print("Average recovery attempts:   ", metrics["average_recovery_attempts"])
    print()

    if errors:
        print("UNEXPECTED ERRORS")
        print("-" * 72)

        for error in errors:
            print(
                error["invoice_id"],
                error["type"],
                error["error"],
            )

        print()

    action_pairs = Counter(
        (
            result.ai_action,
            result.deterministic_action,
            result.result,
        )
        for result in results
    )

    print("AI ? DETERMINISTIC POLICY PAIRS")
    print("-" * 72)

    for (ai_action, policy_action, result), count in sorted(
        action_pairs.items(),
        key=lambda item: (
            str(item[0][0]),
            str(item[0][1]),
            str(item[0][2]),
        ),
    ):
        print(
            f"{count:02d}x "
            f"AI={ai_action} "
            f"POLICY={policy_action} "
            f"RESULT={result}"
        )

    print()
    print("=" * 72)

    if len(errors) > 0:
        raise SystemExit(
            "LIVE AI BENCHMARK FAILED: unexpected execution errors occurred."
        )

    if len(results) != 60:
        raise SystemExit(
            "LIVE AI BENCHMARK INCOMPLETE: fewer than 60 cases reconciled."
        )

    if len(audit_rows) != 60:
        raise SystemExit(
            "LIVE AI BENCHMARK FAILED: expected 60 ai_policy_check audit rows."
        )

    print("LIVE AI 60-CASE RECONCILIATION COMPLETED")
    print()
    print("IMPORTANT:")
    print("  AI recommendations were advisory only.")
    print("  Deterministic policy remained authoritative.")
    print("  No AI recommendation was executed.")
    print("=" * 72)


if __name__ == "__main__":
    main()


