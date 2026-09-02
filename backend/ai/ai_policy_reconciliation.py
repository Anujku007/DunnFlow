from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.ai.recovery_advisor import (
    AIRecoveryRecommendation,
    AIUnavailableResult,
    RecoveryAdvisor,
)
from backend.ai.recovery_context import (
    RecoveryContext,
    build_recovery_context,
)
from backend.data.db import log_audit_entry


@dataclass(frozen=True)
class AIPolicyReconciliation:
    """
    Compare AI advice with the deterministic DunnFlow decision.

    This boundary is advisory only.

    The deterministic decision is always the final authority.
    AI output can agree, disagree, or be unavailable, but it
    can never replace, modify, authorize, or execute the
    deterministic recovery decision.
    """

    invoice_id: str
    ai_available: bool
    ai_action: str | None
    deterministic_action: str
    result: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_id": self.invoice_id,
            "ai_available": self.ai_available,
            "ai_action": self.ai_action,
            "deterministic_action": self.deterministic_action,
            "result": self.result,
            "detail": self.detail,
        }


def reconcile_ai_with_policy(
    *,
    context: RecoveryContext,
    deterministic_decision: dict[str, Any],
    advisor: RecoveryAdvisor,
    audit_logger=log_audit_entry,
) -> AIPolicyReconciliation:
    """
    Compare one AI recommendation with one deterministic decision.

    IMPORTANT:
        This function never changes deterministic_decision.

    The value in deterministic_decision["action_type"] remains the
    only action that downstream scheduling/execution may use.
    """

    invoice_id = context.invoice["invoice_id"]

    deterministic_action = str(
        deterministic_decision.get(
            "action_type",
            "no_action",
        )
    )

    ai_result = advisor.recommend(context)

    if isinstance(ai_result, AIUnavailableResult):
        result = AIPolicyReconciliation(
            invoice_id=invoice_id,
            ai_available=False,
            ai_action=None,
            deterministic_action=deterministic_action,
            result="ai_unavailable",
            detail=(
                "AI advice was unavailable. "
                "Deterministic policy remains the final authority. "
                f"Reason: {ai_result.reason}"
            ),
        )

        audit_logger(
            {
                "batch_id": context.invoice.get("batch_id"),
                "subscription_id": context.subscription.get(
                    "subscription_id"
                ),
                "invoice_id": invoice_id,
                "payment_attempt_id": None,
                "stage": "ai_policy_check",
                "failure_category": context.failure_category,
                "action_taken": deterministic_action,
                "guardrail_hit": None,
                "result": "ai_unavailable",
                "detail": result.detail,
            }
        )

        return result

    if not isinstance(ai_result, AIRecoveryRecommendation):
        raise TypeError(
            "RecoveryAdvisor returned an unsupported result type."
        )

    ai_action = ai_result.recommended_action

    if ai_action == deterministic_action:
        result = "agreement"
        detail = (
            f"AI recommended '{ai_action}' and deterministic policy "
            f"selected '{deterministic_action}'. "
            "Deterministic policy remains the final authority."
        )
    else:
        result = "disagreement"
        detail = (
            f"AI recommended '{ai_action}' but deterministic policy "
            f"selected '{deterministic_action}'. "
            "AI recommendation was not applied; deterministic policy "
            "remains the final authority."
        )

    reconciliation = AIPolicyReconciliation(
        invoice_id=invoice_id,
        ai_available=True,
        ai_action=ai_action,
        deterministic_action=deterministic_action,
        result=result,
        detail=detail,
    )

    audit_logger(
        {
            "batch_id": context.invoice.get("batch_id"),
            "subscription_id": context.subscription.get(
                "subscription_id"
            ),
            "invoice_id": invoice_id,
            "payment_attempt_id": None,
            "stage": "ai_policy_check",
            "failure_category": context.failure_category,
            "action_taken": deterministic_action,
            "guardrail_hit": None,
            "result": result,
            "detail": detail,
        }
    )

    return reconciliation


def reconcile_invoice(
    *,
    invoice_id: str,
    deterministic_decision: dict[str, Any],
    advisor: RecoveryAdvisor,
    as_of=None,
) -> AIPolicyReconciliation:
    """
    Build deterministic context and reconcile AI advice against
    an already-created deterministic decision.

    No decision is created or modified here.
    No payment is executed here.
    """

    context = build_recovery_context(
        invoice_id,
        as_of=as_of,
    )

    return reconcile_ai_with_policy(
        context=context,
        deterministic_decision=deterministic_decision,
        advisor=advisor,
    )
