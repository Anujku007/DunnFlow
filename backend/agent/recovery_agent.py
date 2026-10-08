from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from backend.data.db import (
    get_batch_run,
    get_batch_metrics,
    get_recovery_actions,
    get_invoice,
    get_payment_attempts,
    get_revenue_events,
    init_db,
    log_audit_entry,
)
from backend.modules.detection import detect_revenue_at_risk
from backend.modules.diagnosis import diagnose_invoice
from backend.modules.decision_engine import decide_for_invoice
from backend.modules.scheduler import schedule_batch
from backend.modules.execution import execute_due_actions
from backend.modules.outcome_tracker import summarize_batch_outcomes
from backend.ai.ai_policy_reconciliation import reconcile_invoice
from backend.ai.recovery_context import build_recovery_context
from backend.ai.recovery_advisor import RecoveryAdvisor


class AgentState(str, Enum):
    OBSERVE = "observe"
    DIAGNOSE = "diagnose"
    RECOMMEND = "recommend"
    PRIORITIZE = "prioritize"
    AUTHORIZE = "authorize"
    SCHEDULE = "schedule"
    EXECUTE = "execute"
    VERIFY = "verify"
    MEASURE = "measure"
    STOP = "stop"
    CONTINUE = "continue"
    ESCALATE = "escalate"


@dataclass
class RecoveryAgentContext:
    batch_id: str
    invoice_id: str | None = None
    state: AgentState = AgentState.OBSERVE
    history: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)


class RecoveryAgent:
    """Thin agentic orchestration boundary for DunnFlow.

    The agent coordinates existing DunnFlow modules. Deterministic policy
    remains authoritative for financial recovery decisions, and execution
    remains inside the existing guarded execution engine.
    """

    def __init__(
        self,
        batch_id: str,
        invoice_id: str | None = None,
        ai_advisor: RecoveryAdvisor | None = None,
    ):
        self.context = RecoveryAgentContext(
            batch_id=batch_id,
            invoice_id=invoice_id,
        )
        self.ai_advisor = ai_advisor

    def transition(self, state: AgentState) -> AgentState:
        self.context.state = state
        self.context.history.append(state.value)
        return state

    def observe(self) -> dict[str, Any]:
        self.transition(AgentState.OBSERVE)

        batch = get_batch_run(self.context.batch_id)
        if not batch:
            raise ValueError(
                f"Batch '{self.context.batch_id}' does not exist."
            )

        detection = detect_revenue_at_risk(self.context.batch_id)
        self.context.result["detection"] = detection
        return detection

    def diagnose(self, invoice_id: str) -> dict[str, Any]:
        self.context.invoice_id = invoice_id
        self.transition(AgentState.DIAGNOSE)

        diagnosis = diagnose_invoice(invoice_id)
        self.context.result.setdefault("diagnoses", []).append(diagnosis)
        return diagnosis

    def recommend(
        self,
        invoice_id: str,
        *,
        as_of=None,
    ) -> Any:
        self.context.invoice_id = invoice_id
        self.transition(AgentState.RECOMMEND)

        if self.ai_advisor is None:
            result = {
                "status": "ai_unavailable",
                "reason": "No AI advisor configured.",
            }
            self.context.result.setdefault(
                "ai_recommendations", []
            ).append(result)
            return result

        recovery_context = build_recovery_context(
            invoice_id,
            as_of=as_of,
        )

        recommendation = self.ai_advisor.recommend(
            recovery_context
        )

        if hasattr(recommendation, "__dict__"):
            result = dict(recommendation.__dict__)
        else:
            result = {
                "status": "ai_unavailable",
                "reason": str(recommendation),
            }

        self.context.result.setdefault(
            "ai_recommendations", []
        ).append(result)

        return recommendation

    def prioritize(
        self,
        opportunities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Rank recovery opportunities using advisory AI priority scores.

        AI priority affects ordering only. It never changes the
        deterministic recovery action or authorization decision.

        When AI is unavailable, the original detection order is preserved.
        Ties preserve the original detection order.
        """

        self.transition(AgentState.PRIORITIZE)

        recommendations = self.context.result.get(
            "ai_recommendations",
            [],
        )

        ranked = []

        for index, opportunity in enumerate(opportunities):
            invoice_id = opportunity.get("invoice_id")
            if not invoice_id:
                continue

            recommendation = (
                recommendations[index]
                if index < len(recommendations)
                else None
            )

            if recommendation is None:
                priority_score = None
                urgency = None
                ai_available = False

            elif isinstance(recommendation, dict):
                priority_score = recommendation.get(
                    "priority_score"
                )
                urgency = recommendation.get("urgency")
                ai_available = isinstance(
                    priority_score,
                    int,
                )

            else:
                priority_score = getattr(
                    recommendation,
                    "priority_score",
                    None,
                )
                urgency = getattr(
                    recommendation,
                    "urgency",
                    None,
                )
                ai_available = isinstance(
                    priority_score,
                    int,
                )

            ranked.append(
                {
                    "invoice_id": invoice_id,
                    "priority_score": (
                        priority_score
                        if ai_available
                        else None
                    ),
                    "urgency": (
                        urgency
                        if ai_available
                        else None
                    ),
                    "ai_available": ai_available,
                    "original_index": index,
                    "opportunity": opportunity,
                }
            )

        if any(
            item["ai_available"]
            and isinstance(item["priority_score"], int)
            for item in ranked
        ):
            ranked.sort(
                key=lambda item: (
                    not item["ai_available"],
                    -item["priority_score"]
                    if isinstance(
                        item["priority_score"],
                        int,
                    )
                    else 0,
                    item["original_index"],
                )
            )

        self.context.result[
            "prioritized_opportunities"
        ] = ranked

        return ranked

    def authorize(
        self,
        invoice_id: str,
        *,
        as_of=None,
    ) -> dict[str, Any]:
        """
        Authorize one recovery opportunity.

        Deterministic policy is the only authority for the final
        recovery action. AI advice may be reconciled for auditability,
        but it can never replace or modify the deterministic decision.
        """

        self.context.invoice_id = invoice_id
        self.transition(AgentState.AUTHORIZE)

        decision = decide_for_invoice(
            invoice_id,
            persist=True,
            as_of=as_of,
        )

        self.context.result.setdefault(
            "decisions",
            [],
        ).append(decision)

        if self.ai_advisor is not None:
            reconciliation = reconcile_invoice(
                invoice_id=invoice_id,
                deterministic_decision=decision,
                advisor=self.ai_advisor,
                as_of=as_of,
            )

            if hasattr(reconciliation, "to_dict"):
                reconciliation_result = (
                    reconciliation.to_dict()
                )
            elif hasattr(reconciliation, "__dict__"):
                reconciliation_result = dict(
                    reconciliation.__dict__
                )
            else:
                reconciliation_result = {
                    "result": str(reconciliation)
                }

            self.context.result.setdefault(
                "ai_policy_reconciliation",
                [],
            ).append(reconciliation_result)

        return decision

    def schedule(self, *, as_of=None) -> dict[str, Any]:
        self.transition(AgentState.SCHEDULE)

        scheduled = schedule_batch(
            self.context.batch_id,
            as_of=as_of,
        )
        self.context.result["schedule"] = scheduled
        return scheduled

    def execute(self, *, as_of=None) -> dict[str, Any]:
        self.transition(AgentState.EXECUTE)

        execution = execute_due_actions(
            self.context.batch_id,
            as_of=as_of,
        )
        self.context.result.setdefault("executions", []).append(execution)
        return execution

    def evaluate_stopping_rule(
        self,
        outcome: dict[str, Any],
    ) -> AgentState:
        """Apply deterministic stopping/escalation rules.

        The outcome tracker is the source of truth. AI recommendations
        never determine whether recovery may continue.
        """
        outcome_type = outcome.get("outcome")

        if outcome_type == "recovered":
            return AgentState.STOP

        if outcome_type == "manual_review":
            return AgentState.ESCALATE

        if outcome_type in {
            "blocked",
            "exhausted",
            "not_found",
        }:
            return AgentState.STOP

        if outcome_type == "in_progress":
            return AgentState.CONTINUE

        # Fail closed for unknown or malformed outcomes.
        return AgentState.STOP

    def escalate(
        self,
        invoice_outcome: dict[str, Any],
    ) -> dict[str, Any]:
        """Create an auditable human-review handoff.

        Escalation is deterministic and operational only. It never
        executes a payment or changes the deterministic recovery action.
        """
        self.transition(AgentState.ESCALATE)

        invoice_id = invoice_outcome.get("invoice_id")

        if not invoice_id:
            result = {
                "status": "escalation_failed",
                "reason": "Cannot escalate without an invoice_id.",
            }
            self.context.result["escalation"] = result
            return result

        actions = get_recovery_actions(
            batch_id=self.context.batch_id,
            invoice_id=invoice_id,
        )

        manual_review_actions = [
            action
            for action in actions
            if action.get("action_type") == "manual_review"
        ]

        action_id = (
            manual_review_actions[-1].get("action_id")
            if manual_review_actions
            else None
        )

        audit_id = log_audit_entry(
            {
                "batch_id": self.context.batch_id,
                "invoice_id": invoice_id,
                "stage": "escalation",
                "action_taken": "manual_review",
                "result": "escalated",
                "detail": (
                    "Recovery requires human review. "
                    "No automated financial action will be executed."
                ),
            }
        )

        result = {
            "status": "escalated",
            "invoice_id": invoice_id,
            "action_id": action_id,
            "audit_id": audit_id,
            "reason": (
                "Manual review required; automated financial action "
                "was not executed."
            ),
        }

        self.context.result["escalation"] = result
        return result

    def measure(self) -> dict[str, Any]:
        """Measure realized revenue recovery using authoritative metrics."""
        self.transition(AgentState.MEASURE)

        metrics = get_batch_metrics(
            self.context.batch_id
        )

        historical_amount = int(
            metrics.get("historical_amount_at_risk", 0)
        )

        amount_recovered = int(
            metrics.get("amount_recovered", 0)
        )

        current_amount_at_risk = max(
            historical_amount - amount_recovered,
            0,
        )

        measurement = {
            "batch_id": self.context.batch_id,
            "historical_amount_at_risk": historical_amount,
            "amount_recovered": amount_recovered,
            "recovery_rate_pct": float(
                metrics.get("recovery_rate_pct", 0.0)
            ),
            "current_amount_at_risk": current_amount_at_risk,
            "recovered_count": int(
                metrics.get("recovered_count", 0)
            ),
            "total_invoices": int(
                metrics.get("outcome_count_total", 0)
            ),
            "in_progress_count": int(
                metrics.get("in_progress_count", 0)
            ),
            "blocked_count": int(
                metrics.get("blocked_count", 0)
            ),
            "exhausted_count": int(
                metrics.get("exhausted_count", 0)
            ),
            "manual_review_count": int(
                metrics.get("manual_review_count", 0)
            ),
            "guardrail_blocks": int(
                metrics.get("guardrail_blocks", 0)
            ),
            "measurement_source": "get_batch_metrics",
            "financial_truth": "recovery_confirmed",
        }

        self.context.result["measurement"] = measurement

        return measurement

    def verify(self) -> dict[str, Any]:
        self.transition(AgentState.VERIFY)

        outcome = summarize_batch_outcomes(self.context.batch_id)
        self.context.result["outcome"] = outcome

        outcomes = outcome.get("outcomes", [])

        if self.context.invoice_id:
            invoice_outcome = next(
                (
                    item
                    for item in outcomes
                    if item.get("invoice_id")
                    == self.context.invoice_id
                ),
                None,
            )
        else:
            invoice_outcome = None

        # --------------------------------------------------------------
        # Financial recovery verification
        # --------------------------------------------------------------
        #
        # Execution success is NOT financial truth.
        #
        # Recovery is verified only when:
        #
        #   1. a recovery_confirmed revenue event exists,
        #   2. the invoice is paid, and
        #   3. a successful recovery payment attempt exists.
        #
        # This deliberately fails closed. An execution result alone
        # cannot be treated as recovered revenue.
        # --------------------------------------------------------------

        verification = {
            "invoice_id": self.context.invoice_id,
            "invoice_status": None,
            "recovery_confirmed": False,
            "recovery_event_id": None,
            "recovered_amount": 0,
            "successful_payment_attempt": False,
            "verified_recovery": False,
            "verification_source": "recovery_confirmed",
        }

        if self.context.invoice_id:
            invoice = get_invoice(
                self.context.invoice_id
            )

            if invoice:
                verification["invoice_status"] = invoice.get(
                    "status"
                )

                recovery_events = get_revenue_events(
                    invoice_id=self.context.invoice_id,
                    event_type="recovery_confirmed",
                )

                recovery_event = (
                    recovery_events[-1]
                    if recovery_events
                    else None
                )

                attempts = get_payment_attempts(
                    invoice_id=self.context.invoice_id
                )

                successful_payment_attempt = any(
                    attempt.get("result") == "success"
                    and attempt.get("attempt_type")
                    in {
                        "auto_retry",
                        "manual_retry",
                        "recovery_payment",
                        "customer_payment",
                    }
                    for attempt in attempts
                )

                verification[
                    "successful_payment_attempt"
                ] = successful_payment_attempt

                if recovery_event:
                    verification[
                        "recovery_confirmed"
                    ] = True

                    verification[
                        "recovery_event_id"
                    ] = recovery_event.get(
                        "event_id"
                    )

                    verification[
                        "recovered_amount"
                    ] = int(
                        recovery_event.get(
                            "amount",
                            0,
                        )
                    )

                verification[
                    "verified_recovery"
                ] = (
                    verification[
                        "recovery_confirmed"
                    ]
                    and verification[
                        "invoice_status"
                    ] == "paid"
                    and verification[
                        "successful_payment_attempt"
                    ]
                )

        self.context.result[
            "verification"
        ] = verification

        # --------------------------------------------------------------
        # Deterministic stopping rule
        # --------------------------------------------------------------

        if invoice_outcome is not None:
            stopping_state = self.evaluate_stopping_rule(
                invoice_outcome
            )
        else:
            stopping_state = AgentState.STOP

        self.context.result["stopping_rule"] = {
            "outcome": (
                invoice_outcome.get("outcome")
                if invoice_outcome
                else None
            ),
            "state": stopping_state.value,
        }

        if (
            invoice_outcome is not None
            and stopping_state == AgentState.ESCALATE
        ):
            self.escalate(invoice_outcome)
        else:
            self.transition(stopping_state)

        return outcome

    def run_invoice(
        self,
        invoice_id: str,
        *,
        as_of=None,
    ) -> RecoveryAgentContext:
        """Run the decision portion of recovery for one invoice."""

        self.observe()
        self.diagnose(invoice_id)
        self.recommend(invoice_id, as_of=as_of)
        self.authorize(invoice_id, as_of=as_of)

        self.transition(AgentState.CONTINUE)
        return self.context

    def prepare_batch(
        self,
        *,
        as_of=None,
    ) -> RecoveryAgentContext:
        """
        Prepare one batch for the authoritative DunnFlow orchestrator.

        This performs the agentic reasoning/planning boundary only.
        It does not schedule or execute payments.

        Financial execution remains owned by the existing authoritative
        orchestrator and guarded execution engine.
        """

        init_db()

        self.observe()

        detection = self.context.result.get(
            "detection",
            {},
        )

        opportunities = detection.get(
            "opportunities",
            [],
        )

        for item in opportunities:
            invoice_id = item.get("invoice_id")

            if not invoice_id:
                continue

            self.diagnose(invoice_id)

            self.recommend(
                invoice_id,
                as_of=as_of,
            )

        ranked_opportunities = self.prioritize(
            opportunities
        )

        self.context.result[
            "agent_ready"
        ] = True

        self.context.result[
            "execution_authority"
        ] = "deterministic_orchestrator"

        self.context.result[
            "ai_authority"
        ] = "advisory_only"

        self.context.result[
            "financial_authority"
        ] = "deterministic_policy"

        self.context.result[
            "ranked_opportunities"
        ] = ranked_opportunities

        self.transition(
            AgentState.CONTINUE
        )

        return self.context

    def run_authorized_batch(
        self,
        *,
        as_of=None,
        ai_advisor=None,
    ) -> dict[str, Any]:
        """
        Prepare the recovery plan and hand financial execution to the
        existing deterministic orchestrator.

        The RecoveryAgent is NOT a second execution engine.

        Responsibilities of this method:

            agent planning
                ->
            deterministic orchestrator handoff

        Financial execution, scheduling, verification, stopping rules,
        escalation, webhook processing, and recovered-revenue accounting
        remain owned by the existing DunnFlow architecture.
        """

        planning_context = self.prepare_batch(
            as_of=as_of,
        )

        if not planning_context.result.get(
            "agent_ready",
            False,
        ):
            raise RuntimeError(
                "RecoveryAgent planning did not reach agent_ready state."
            )

        if (
            planning_context.result.get(
                "execution_authority"
            )
            != "deterministic_orchestrator"
        ):
            raise RuntimeError(
                "RecoveryAgent execution authority is not "
                "deterministic_orchestrator."
            )

        if (
            planning_context.result.get(
                "financial_authority"
            )
            != "deterministic_policy"
        ):
            raise RuntimeError(
                "RecoveryAgent financial authority is not "
                "deterministic_policy."
            )

        if (
            planning_context.result.get(
                "ai_authority"
            )
            != "advisory_only"
        ):
            raise RuntimeError(
                "RecoveryAgent AI authority is not advisory_only."
            )

        # Import lazily to avoid a module-level circular dependency.
        from orchestrator import run_batch as run_deterministic_batch

        execution_result = run_deterministic_batch(
            self.context.batch_id,
            as_of=as_of,
            ai_advisor=(
                None
                if planning_context.result.get(
                    "ai_recommendations"
                )
                else ai_advisor
            ),
            agent_plan={
                "agent_ready": True,
                "execution_authority": (
                    planning_context.result[
                        "execution_authority"
                    ]
                ),
                "financial_authority": (
                    planning_context.result[
                        "financial_authority"
                    ]
                ),
                "ai_authority": (
                    planning_context.result[
                        "ai_authority"
                    ]
                ),
                "ranked_opportunities": (
                    planning_context.result.get(
                        "ranked_opportunities",
                        [],
                    )
                ),
                "ai_recommendations": (
                    planning_context.result.get(
                        "ai_recommendations",
                        [],
                    )
                ),
                "agent_advisory_source": (
                    "recovery_agent_single_pass"
                ),
            },
        )

        return {
            "batch_id": self.context.batch_id,
            "agent": {
                "state": planning_context.state.value,
                "history": list(
                    planning_context.history
                ),
                "agent_ready": True,
                "execution_authority": (
                    planning_context.result[
                        "execution_authority"
                    ]
                ),
                "financial_authority": (
                    planning_context.result[
                        "financial_authority"
                    ]
                ),
                "ai_authority": (
                    planning_context.result[
                        "ai_authority"
                    ]
                ),
                "ranked_opportunities": (
                    planning_context.result.get(
                        "ranked_opportunities",
                        [],
                    )
                ),
                "diagnoses": (
                    planning_context.result.get(
                        "diagnoses",
                        [],
                    )
                ),
                "ai_recommendations": (
                    planning_context.result.get(
                        "ai_recommendations",
                        [],
                    )
                ),
            },
            "execution": execution_result,
        }

    def run_batch(
        self,
        *,
        as_of=None,
    ) -> RecoveryAgentContext:
        """Run the complete orchestration cycle for one batch."""

        init_db()
        self.observe()

        detection = self.context.result["detection"]

        opportunities = detection.get("opportunities", [])

        for item in opportunities:
            invoice_id = item.get("invoice_id")
            if not invoice_id:
                continue

            self.diagnose(invoice_id)
            self.recommend(invoice_id, as_of=as_of)

        ranked_opportunities = self.prioritize(
            opportunities
        )

        for ranked_item in ranked_opportunities:
            invoice_id = ranked_item["invoice_id"]

            self.authorize(
                invoice_id,
                as_of=as_of,
            )

        self.schedule(as_of=as_of)
        self.execute(as_of=as_of)
        self.verify()
        self.measure()

        self.transition(AgentState.STOP)
        return self.context
