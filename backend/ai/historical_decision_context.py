
"""DunnFlow historical decision context builder.

This module builds read-only historical evidence for the AI recovery advisor.

It does NOT:
- modify the database
- create recovery actions
- execute payments
- modify deterministic decisions
- modify webhook handling

Historical evidence is derived from the existing:
- invoices
- recovery_actions
- revenue_events
- audit_log

The purpose is to let AI reason from what DunnFlow decided previously
and what happened afterward.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.data.db import (
    get_audit_log,
    get_invoices,
    get_recovery_actions,
    get_revenue_events,
)


_AI_RECOMMENDATION_PATTERN = re.compile(
    r"AI recommended ['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HistoricalCase:
    """Compact historical decision/outcome record."""

    invoice_id: str
    failure_category: str | None
    amount: int
    deterministic_action: str | None
    deterministic_status: str | None
    guardrail_hit: str | None
    ai_recommendation: str | None
    ai_result: str | None
    outcome: str
    recovered_amount: int
    recovery_confirmed: bool
    payment_captured: bool
    created_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HistoricalDecisionContext:
    """Historical evidence supplied to the AI advisor."""

    current_invoice_id: str
    failure_category: str | None
    similar_case_count: int

    historical_cases: list[dict[str, Any]]

    action_statistics: dict[str, dict[str, Any]]

    ai_statistics: dict[str, Any]

    # Historical outcomes grouped by the action previously recommended
    # by AI. This is observational learning evidence only.
    ai_action_statistics: dict[str, dict[str, Any]]

    outcome_statistics: dict[str, Any]

    learning_signal: dict[str, Any]
    failure_category_learning: dict[str, Any] = field(default_factory=dict)
    # Amount-band-specific historical learning is advisory only.
    amount_band_learning: dict[str, Any] = field(default_factory=dict)

    # Customer-level historical behavior is advisory evidence only.
    customer_behavior: dict[str, Any] = field(default_factory=dict)

    # Recency-aware historical evidence is advisory only.
    recency_learning: dict[str, Any] = field(default_factory=dict)

    # Combined historical evidence synthesis is advisory only.
    historical_evidence_summary: dict[str, Any] = field(default_factory=dict)

    # Cross-dimension historical evidence consistency is advisory only.
    historical_evidence_consistency: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _extract_ai_recommendation(detail: str | None) -> str | None:
    """Extract the AI recommended action from an audit detail string."""

    if not detail:
        return None

    match = _AI_RECOMMENDATION_PATTERN.search(str(detail))

    if not match:
        return None

    return match.group(1)


def _latest_decision_action(
    recovery_actions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the latest persisted recovery decision."""

    if not recovery_actions:
        return None

    return recovery_actions[-1]


def _ai_history(
    audit_history: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    """Return latest AI recommendation and reconciliation result."""

    ai_rows = [
        row
        for row in audit_history
        if str(row.get("stage", "")).lower()
        in {
            "ai_policy_check",
            "ai_reconciliation",
        }
    ]

    if not ai_rows:
        return None, None

    latest = ai_rows[-1]

    recommendation = _extract_ai_recommendation(
        latest.get("detail")
    )

    result = latest.get("result")

    return (
        recommendation,
        str(result) if result is not None else None,
    )


def _determine_outcome(
    recovery_actions: list[dict[str, Any]],
    revenue_events: list[dict[str, Any]],
) -> tuple[str, int, bool, bool]:
    """Determine the financial outcome of a historical recovery case."""

    event_types = {
        str(event.get("event_type", "")).lower()
        for event in revenue_events
    }

    payment_captured = (
        "payment_captured" in event_types
    )

    recovery_confirmed = (
        "recovery_confirmed" in event_types
    )

    recovered_amount = sum(
        int(event.get("amount") or 0)
        for event in revenue_events
        if str(event.get("event_type", "")).lower()
        in {
            "payment_captured",
            "recovery_confirmed",
        }
    )

    if recovery_confirmed or payment_captured:
        return (
            "recovered",
            recovered_amount,
            recovery_confirmed,
            payment_captured,
        )

    action_statuses = {
        str(action.get("status", "")).lower()
        for action in recovery_actions
    }

    if "blocked" in action_statuses:
        return (
            "blocked",
            0,
            False,
            False,
        )

    if "cancelled" in action_statuses:
        return (
            "no_action",
            0,
            False,
            False,
        )

    if "executed" in action_statuses:
        return (
            "executed_no_recovery",
            0,
            False,
            False,
        )

    return (
        "in_progress",
        0,
        False,
        False,
    )


def _build_historical_case(
    invoice: dict[str, Any],
) -> HistoricalCase:
    """Build one compact historical case from existing DB state."""

    invoice_id = str(invoice["invoice_id"])

    recovery_actions = get_recovery_actions(
        invoice_id=invoice_id
    )

    audit_history = get_audit_log(
        invoice_id=invoice_id
    )

    revenue_events = get_revenue_events(
        invoice_id=invoice_id
    )

    decision = _latest_decision_action(
        recovery_actions
    )

    ai_recommendation, ai_result = _ai_history(
        audit_history
    )

    (
        outcome,
        recovered_amount,
        recovery_confirmed,
        payment_captured,
    ) = _determine_outcome(
        recovery_actions,
        revenue_events,
    )

    return HistoricalCase(
        invoice_id=invoice_id,
        failure_category=invoice.get(
            "failure_category"
        ),
        amount=int(invoice.get("amount") or 0),
        deterministic_action=(
            decision.get("action_type")
            if decision
            else None
        ),
        deterministic_status=(
            decision.get("status")
            if decision
            else None
        ),
        guardrail_hit=(
            decision.get("guardrail_hit")
            if decision
            else None
        ),
        ai_recommendation=ai_recommendation,
        ai_result=ai_result,
        outcome=outcome,
        recovered_amount=recovered_amount,
        recovery_confirmed=recovery_confirmed,
        payment_captured=payment_captured,
        created_at=(
            decision.get("created_at")
            if decision
            else None
        ),
    )




def _amount_band(amount: int) -> str:
    """Return a deterministic bounded amount band for similarity scoring.

    This is a contextual similarity feature only. It does not evaluate
    whether an invoice is financially good or bad and has no execution
    authority.
    """

    value = max(0, int(amount or 0))

    if value < 50000:
        return "small"

    if value < 100000:
        return "medium"

    if value < 250000:
        return "large"

    return "very_large"


def _historical_similarity_score(
    current: HistoricalCase,
    candidate: HistoricalCase,
) -> int:
    """Calculate a bounded contextual similarity score.

    Similarity uses information available from the case itself and does not
    use historical outcomes, recovered amounts, or AI recommendations as
    ranking signals.

    Score:
        failure category       50
        deterministic action   25
        status/context         10
        amount band             10
        recency/context         5

    The score is advisory ranking metadata only.
    """

    score = 0

    if (
        current.failure_category
        and candidate.failure_category
        and current.failure_category == candidate.failure_category
    ):
        score += 50

    if (
        current.deterministic_action
        and candidate.deterministic_action
        and current.deterministic_action
        == candidate.deterministic_action
    ):
        score += 25

    if (
        current.deterministic_status
        and candidate.deterministic_status
        and current.deterministic_status
        == candidate.deterministic_status
    ):
        score += 10

    if _amount_band(current.amount) == _amount_band(candidate.amount):
        score += 10

    if current.created_at and candidate.created_at:
        score += 5

    return min(100, max(0, score))

def _build_action_statistics(
    cases: list[HistoricalCase],
) -> dict[str, dict[str, Any]]:
    """Calculate historical success statistics by deterministic action."""

    grouped: dict[str, list[HistoricalCase]] = {}

    for case in cases:
        action = (
            case.deterministic_action
            or "unknown"
        )

        grouped.setdefault(
            action,
            [],
        ).append(case)

    statistics: dict[str, dict[str, Any]] = {}

    for action, action_cases in grouped.items():
        recovered = sum(
            1
            for case in action_cases
            if case.outcome == "recovered"
        )

        total = len(action_cases)

        statistics[action] = {
            "total_cases": total,
            "recovered_cases": recovered,
            "recovery_rate": (
                recovered / total
                if total
                else 0.0
            ),
            "blocked_cases": sum(
                1
                for case in action_cases
                if case.outcome == "blocked"
            ),
            "in_progress_cases": sum(
                1
                for case in action_cases
                if case.outcome == "in_progress"
            ),
        }

    return statistics


def _build_ai_statistics(
    cases: list[HistoricalCase],
) -> dict[str, Any]:
    """Calculate historical AI recommendation/agreement statistics."""

    ai_cases = [
        case
        for case in cases
        if case.ai_recommendation
    ]

    agreements = sum(
        1
        for case in ai_cases
        if case.ai_result == "agreement"
    )

    disagreements = sum(
        1
        for case in ai_cases
        if case.ai_result == "disagreement"
    )

    recovered_after_ai = sum(
        1
        for case in ai_cases
        if case.outcome == "recovered"
    )

    total = len(ai_cases)

    return {
        "cases_with_ai_recommendation": total,
        "agreement_count": agreements,
        "disagreement_count": disagreements,
        "agreement_rate": (
            agreements / total
            if total
            else 0.0
        ),
        "recovered_cases_after_ai_review": recovered_after_ai,
        "recovery_rate_after_ai_review": (
            recovered_after_ai / total
            if total
            else 0.0
        ),
    }


def _ai_action_evidence_quality(sample_size: int) -> str:
    """Classify historical evidence depth using deterministic episode counts.

    This is an evidence-depth heuristic, not a statistical confidence score.
    It does not determine whether an action is good or bad and does not grant
    execution authority.
    """

    if sample_size <= 0:
        return "insufficient"

    if sample_size <= 2:
        return "limited"

    if sample_size <= 9:
        return "moderate"

    return "strong"


def _build_ai_action_statistics(
    cases: list[HistoricalCase],
) -> dict[str, dict[str, Any]]:
    """Calculate advisory outcome correlation for AI recommendations.

    Each HistoricalCase represents one historical invoice episode.
    Repeated AI policy-review audit records for the same invoice are
    therefore not counted independently here.

    Financial outcomes remain attributed to deterministic policy.
    These statistics are observational learning evidence only.
    """

    grouped: dict[str, list[HistoricalCase]] = {}

    for case in cases:
        action = case.ai_recommendation

        if not action:
            continue

        grouped.setdefault(action, []).append(case)

    statistics: dict[str, dict[str, Any]] = {}

    for action, action_cases in grouped.items():
        total = len(action_cases)

        recovered = sum(
            1
            for case in action_cases
            if case.outcome == "recovered"
        )

        recovered_amount = sum(
            int(case.recovered_amount or 0)
            for case in action_cases
        )

        blocked = sum(
            1
            for case in action_cases
            if case.outcome == "blocked"
        )

        in_progress = sum(
            1
            for case in action_cases
            if case.outcome == "in_progress"
        )

        agreement = sum(
            1
            for case in action_cases
            if case.ai_result == "agreement"
        )

        disagreement = sum(
            1
            for case in action_cases
            if case.ai_result == "disagreement"
        )

        statistics[action] = {
            "total_cases": total,
            "recovered_cases": recovered,
            "recovery_rate": (
                recovered / total
                if total
                else 0.0
            ),
            "recovered_amount": recovered_amount,
            "blocked_cases": blocked,
            "in_progress_cases": in_progress,
            "agreement_cases": agreement,
            "disagreement_cases": disagreement,

            # Deterministic evidence-depth heuristic only.
            # This is NOT statistical confidence and does not determine
            # whether the historical action is good or bad.
            "evidence_quality": _ai_action_evidence_quality(total),

            # This is observational evidence only.
            "attribution": "advisory_correlation",

            # One HistoricalCase represents one invoice episode.
            "episode_granularity": "invoice",

            # Financial outcomes remain controlled by deterministic policy.
            "financial_authority": "deterministic_policy",
        }

    return statistics


def _build_outcome_statistics(
    cases: list[HistoricalCase],
) -> dict[str, Any]:
    """Calculate historical outcome statistics."""

    total = len(cases)

    recovered = sum(
        1
        for case in cases
        if case.outcome == "recovered"
    )

    blocked = sum(
        1
        for case in cases
        if case.outcome == "blocked"
    )

    in_progress = sum(
        1
        for case in cases
        if case.outcome == "in_progress"
    )

    no_action = sum(
        1
        for case in cases
        if case.outcome == "no_action"
    )

    recovered_amount = sum(
        case.recovered_amount
        for case in cases
    )

    return {
        "total_cases": total,
        "recovered": recovered,
        "blocked": blocked,
        "in_progress": in_progress,
        "no_action": no_action,
        "recovered_amount": recovered_amount,
        "recovery_rate": (
            recovered / total
            if total
            else 0.0
        ),
    }


def _build_learning_signal(
    cases: list[HistoricalCase],
) -> dict[str, Any]:
    """Build a bounded historical learning signal.

    This is evidence for the AI only. It does not alter policy.
    """

    total = len(cases)

    if not total:
        return {
            "available": False,
            "confidence": 0.0,
            "signal": "no_historical_evidence",
        }

    recovered = sum(
        1
        for case in cases
        if case.outcome == "recovered"
    )

    recovery_rate = recovered / total

    if total >= 10:
        confidence = min(
            0.95,
            0.50 + (total / 100),
        )
    elif total >= 3:
        confidence = 0.50
    else:
        confidence = 0.25

    if recovery_rate >= 0.70:
        signal = "historically_favorable"
    elif recovery_rate <= 0.30:
        signal = "historically_unfavorable"
    else:
        signal = "historically_mixed"

    return {
        "available": True,
        "confidence": round(
            confidence,
            3,
        ),
        "signal": signal,
        "sample_size": total,
        "historical_recovery_rate": round(
            recovery_rate,
            3,
        ),
    }




def _build_amount_band_learning(
    current_amount: int,
    historical_cases: list[HistoricalCase],
) -> dict[str, Any]:
    """Build bounded historical learning grouped by amount band.

    This is observational evidence for the AI advisor only.

    Historical outcomes are never used to alter deterministic policy.
    """

    current_band = _amount_band(
        current_amount
    )

    grouped: dict[str, list[HistoricalCase]] = {}

    for case in historical_cases:
        band = _amount_band(
            case.amount
        )

        grouped.setdefault(
            band,
            [],
        ).append(case)

    bands: dict[str, dict[str, Any]] = {}

    for band, cases in grouped.items():

        total = len(cases)

        recovered = sum(
            1
            for case in cases
            if case.outcome == "recovered"
        )

        failed = sum(
            1
            for case in cases
            if case.outcome in {
                "failed",
                "exhausted",
                "blocked",
            }
        )

        in_progress = sum(
            1
            for case in cases
            if case.outcome == "in_progress"
        )

        recovery_rate = (
            recovered / total
            if total
            else None
        )

        action_statistics = _build_action_statistics(
            cases
        )

        bands[band] = {
            "sample_size": total,
            "recovered_count": recovered,
            "failed_count": failed,
            "in_progress_count": in_progress,
            "recovery_rate": (
                round(recovery_rate, 3)
                if recovery_rate is not None
                else None
            ),
            "action_statistics": action_statistics,
        }

    current_band_data = bands.get(
        current_band,
        {
            "sample_size": 0,
            "recovered_count": 0,
            "failed_count": 0,
            "in_progress_count": 0,
            "recovery_rate": None,
            "action_statistics": {},
        },
    )

    sample_size = current_band_data[
        "sample_size"
    ]

    if sample_size == 0:
        evidence_quality = "insufficient"

    elif sample_size <= 2:
        evidence_quality = "limited"

    elif sample_size <= 9:
        evidence_quality = "moderate"

    else:
        evidence_quality = "strong"

    return {
        "available": sample_size > 0,
        "current_amount_band": current_band,
        "sample_size": sample_size,
        "recovered_count": current_band_data[
            "recovered_count"
        ],
        "failed_count": current_band_data[
            "failed_count"
        ],
        "in_progress_count": current_band_data[
            "in_progress_count"
        ],
        "recovery_rate": current_band_data[
            "recovery_rate"
        ],
        "action_statistics": current_band_data[
            "action_statistics"
        ],
        "evidence_quality": evidence_quality,
        "bands": bands,
        "provenance": {
            "attribution": "amount_band_observation",
            "episode_granularity": "invoice",
            "financial_authority": "deterministic_policy",
        },
        "advisory_only": True,
    }


def _build_failure_category_learning(
    failure_category: str | None,
    historical_cases: list[HistoricalCase],
) -> dict[str, Any]:
    """Build bounded failure-category-specific historical learning evidence.

    The historical cases supplied here have already been selected from the
    current invoice's failure category.

    This summary is observational evidence for the AI advisor only.
    It does not modify deterministic policy and has no execution authority.
    """

    category = (
        str(failure_category)
        if failure_category is not None
        else "unclassified"
    )

    category_cases = [
        case
        for case in historical_cases
        if case.failure_category == failure_category
    ]

    action_statistics = _build_action_statistics(
        category_cases
    )

    ai_statistics = _build_ai_statistics(
        category_cases
    )

    ai_action_statistics = _build_ai_action_statistics(
        category_cases
    )

    outcome_statistics = _build_outcome_statistics(
        category_cases
    )

    learning_signal = _build_learning_signal(
        category_cases
    )

    return {
        "available": bool(category_cases),
        "failure_category": category,
        "sample_size": len(category_cases),
        "action_statistics": action_statistics,
        "ai_statistics": ai_statistics,
        "ai_action_statistics": ai_action_statistics,
        "outcome_statistics": outcome_statistics,
        "learning_signal": learning_signal,
        "provenance": {
            "attribution": "advisory_correlation",
            "episode_granularity": "invoice",
            "financial_authority": "deterministic_policy",
        },
        "advisory_only": True,
    }



def _build_customer_behavior(
    current_invoice: dict[str, Any],
    invoices: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build bounded historical behavior for the current customer.

    Customer behavior is observational evidence only.

    The current invoice is always excluded.

    Financial authority remains deterministic policy.
    """

    subscription_id = current_invoice.get("subscription_id")

    if not subscription_id:
        return {
            "available": False,
            "customer_id": None,
            "sample_size": 0,
            "invoice_count": 0,
            "recovered_count": 0,
            "failed_count": 0,
            "in_progress_count": 0,
            "recovery_rate": None,
            "average_attempts": None,
            "behavior_signal": "insufficient_history",
            "evidence_quality": "insufficient",
            "provenance": {
                "attribution": "customer_behavior_observation",
                "episode_granularity": "invoice",
                "financial_authority": "deterministic_policy",
            },
            "advisory_only": True,
        }

    try:
        from backend.data.db import (
            get_subscription,
            get_payment_attempts,
            get_recovery_actions,
        )

        current_subscription = get_subscription(
            str(subscription_id)
        )

    except Exception:
        current_subscription = None
        get_payment_attempts = None
        get_recovery_actions = None

    if not current_subscription:
        return {
            "available": False,
            "customer_id": None,
            "sample_size": 0,
            "invoice_count": 0,
            "recovered_count": 0,
            "failed_count": 0,
            "in_progress_count": 0,
            "recovery_rate": None,
            "average_attempts": None,
            "behavior_signal": "customer_unavailable",
            "evidence_quality": "insufficient",
            "provenance": {
                "attribution": "customer_behavior_observation",
                "episode_granularity": "invoice",
                "financial_authority": "deterministic_policy",
            },
            "advisory_only": True,
        }

    customer_id = current_subscription.get("customer_id")

    if not customer_id:
        return {
            "available": False,
            "customer_id": None,
            "sample_size": 0,
            "invoice_count": 0,
            "recovered_count": 0,
            "failed_count": 0,
            "in_progress_count": 0,
            "recovery_rate": None,
            "average_attempts": None,
            "behavior_signal": "customer_id_unavailable",
            "evidence_quality": "insufficient",
            "provenance": {
                "attribution": "customer_behavior_observation",
                "episode_granularity": "invoice",
                "financial_authority": "deterministic_policy",
            },
            "advisory_only": True,
        }

    # Resolve every subscription belonging to this customer.
    customer_subscriptions = []

    for invoice in invoices:
        sid = invoice.get("subscription_id")

        if not sid:
            continue

        try:
            subscription = get_subscription(str(sid))
        except Exception:
            subscription = None

        if not subscription:
            continue

        if str(subscription.get("customer_id")) != str(customer_id):
            continue

        customer_subscriptions.append(
            str(sid)
        )

    customer_subscription_ids = set(
        customer_subscriptions
    )

    # Historical customer invoices, excluding current invoice.
    customer_invoices = [
        invoice
        for invoice in invoices
        if str(invoice.get("invoice_id"))
        != str(current_invoice.get("invoice_id"))
        and str(invoice.get("subscription_id"))
        in customer_subscription_ids
    ]

    sample_size = len(customer_invoices)

    recovered_count = 0
    failed_count = 0
    in_progress_count = 0
    total_attempts = 0

    for invoice in customer_invoices:

        invoice_id = str(
            invoice.get("invoice_id")
        )

        # Use the existing historical outcome logic so customer behavior
        # does not invent a second definition of financial recovery.
        try:
            recovery_actions = get_recovery_actions(
                invoice_id=invoice_id
            )
        except Exception:
            recovery_actions = []

        try:
            payment_attempts = get_payment_attempts(
                invoice_id=invoice_id
            )
        except Exception:
            payment_attempts = []

        (
            outcome,
            _recovered_amount,
            _recovery_confirmed,
            _payment_captured,
        ) = _determine_outcome(
            recovery_actions,
            payment_attempts,
        )

        if outcome == "recovered":
            recovered_count += 1
        elif outcome == "in_progress":
            in_progress_count += 1
        elif outcome in {
            "executed_no_recovery",
            "blocked",
            "no_action",
        }:
            failed_count += 1

        total_attempts += len(
            payment_attempts or []
        )

    if sample_size == 0:
        return {
            "available": True,
            "customer_id": str(customer_id),
            "sample_size": 0,
            "invoice_count": 0,
            "recovered_count": 0,
            "failed_count": 0,
            "in_progress_count": 0,
            "recovery_rate": None,
            "average_attempts": None,
            "behavior_signal": "insufficient_history",
            "evidence_quality": "insufficient",
            "provenance": {
                "attribution": "customer_behavior_observation",
                "episode_granularity": "invoice",
                "financial_authority": "deterministic_policy",
            },
            "advisory_only": True,
        }

    outcome_count = (
        recovered_count
        + failed_count
        + in_progress_count
    )

    recovery_rate = (
        recovered_count / outcome_count
        if outcome_count
        else None
    )

    average_attempts = (
        total_attempts / sample_size
        if sample_size
        else None
    )

    if sample_size <= 2:
        evidence_quality = "limited"
    elif sample_size <= 9:
        evidence_quality = "moderate"
    else:
        evidence_quality = "strong"

    if recovery_rate is None:
        behavior_signal = "insufficient_outcome_history"
    elif recovery_rate >= 0.70:
        behavior_signal = "historically_favorable"
    elif recovery_rate <= 0.30:
        behavior_signal = "historically_unfavorable"
    else:
        behavior_signal = "historically_mixed"

    return {
        "available": True,
        "customer_id": str(customer_id),
        "sample_size": sample_size,
        "invoice_count": sample_size,
        "recovered_count": recovered_count,
        "failed_count": failed_count,
        "in_progress_count": in_progress_count,
        "recovery_rate": (
            round(recovery_rate, 4)
            if recovery_rate is not None
            else None
        ),
        "average_attempts": (
            round(average_attempts, 4)
            if average_attempts is not None
            else None
        ),
        "behavior_signal": behavior_signal,
        "evidence_quality": evidence_quality,
        "provenance": {
            "attribution": "customer_behavior_observation",
            "episode_granularity": "invoice",
            "financial_authority": "deterministic_policy",
        },
        "advisory_only": True,
    }



def _build_recency_learning(
    historical_cases: list[HistoricalCase],
) -> dict[str, Any]:
    """Build bounded recency-aware historical learning evidence.

    Historical cases are already restricted to the current failure category
    and similarity-ranked by the caller.

    Recency is contextual evidence only.

    It does NOT:
    - modify deterministic policy
    - change recovery actions
    - authorize execution
    - change financial outcomes
    - treat recency as causation
    """

    if not historical_cases:
        return {
            "available": False,
            "sample_size": 0,
            "recent_sample_size": 0,
            "older_sample_size": 0,
            "recent_recovery_rate": None,
            "overall_recovery_rate": None,
            "recency_signal": "insufficient_history",
            "evidence_quality": "insufficient",
            "provenance": {
                "attribution": "recency_observation",
                "episode_granularity": "invoice",
                "financial_authority": "deterministic_policy",
            },
            "advisory_only": True,
        }

    # HistoricalCase.created_at is the deterministic decision timestamp.
    # We deliberately use ordering rather than inventing a wall-clock age
    # when the underlying timestamp is unavailable or malformed.
    dated_cases = [
        case
        for case in historical_cases
        if case.created_at
    ]

    if not dated_cases:
        return {
            "available": True,
            "sample_size": len(historical_cases),
            "recent_sample_size": 0,
            "older_sample_size": 0,
            "recent_recovery_rate": None,
            "overall_recovery_rate": None,
            "recency_signal": "insufficient_timestamps",
            "evidence_quality": "insufficient",
            "provenance": {
                "attribution": "recency_observation",
                "episode_granularity": "invoice",
                "financial_authority": "deterministic_policy",
            },
            "advisory_only": True,
        }

    # Sort deterministically by the supplied historical timestamp.
    # No external current-time dependency is introduced.
    dated_cases = sorted(
        dated_cases,
        key=lambda case: str(case.created_at),
        reverse=True,
    )

    total = len(dated_cases)

    # Define "recent" as the newest half of the available dated episodes,
    # with a minimum of one case. This avoids arbitrary calendar assumptions
    # and works safely with the synthetic benchmark.
    recent_count = max(
        1,
        (total + 1) // 2,
    )

    recent_cases = dated_cases[:recent_count]
    older_cases = dated_cases[recent_count:]

    recent_recovered = sum(
        1
        for case in recent_cases
        if case.outcome == "recovered"
    )

    overall_recovered = sum(
        1
        for case in dated_cases
        if case.outcome == "recovered"
    )

    recent_rate = (
        recent_recovered / len(recent_cases)
        if recent_cases
        else None
    )

    overall_rate = (
        overall_recovered / len(dated_cases)
        if dated_cases
        else None
    )

    if total <= 2:
        evidence_quality = "limited"
    elif total <= 9:
        evidence_quality = "moderate"
    else:
        evidence_quality = "strong"

    if recent_rate is None:
        recency_signal = "insufficient_recent_history"
    elif recent_rate >= 0.70:
        recency_signal = "recently_favorable"
    elif recent_rate <= 0.30:
        recency_signal = "recently_unfavorable"
    else:
        recency_signal = "recently_mixed"

    return {
        "available": True,
        "sample_size": len(historical_cases),
        "dated_sample_size": total,
        "recent_sample_size": len(recent_cases),
        "older_sample_size": len(older_cases),
        "recent_recovery_rate": (
            round(recent_rate, 4)
            if recent_rate is not None
            else None
        ),
        "overall_recovery_rate": (
            round(overall_rate, 4)
            if overall_rate is not None
            else None
        ),
        "recency_signal": recency_signal,
        "evidence_quality": evidence_quality,
        "provenance": {
            "attribution": "recency_observation",
            "episode_granularity": "invoice",
            "financial_authority": "deterministic_policy",
        },
        "advisory_only": True,
    }


def _build_historical_evidence_summary(
    historical_cases: list[HistoricalCase],
    failure_category_learning: dict[str, Any],
    customer_behavior: dict[str, Any],
    amount_band_learning: dict[str, Any],
    recency_learning: dict[str, Any],
) -> dict[str, Any]:
    """Summarize the breadth and quality of historical evidence.

    This is advisory evidence metadata only.

    It does not:
    - choose a financial action
    - override deterministic policy
    - authorize execution
    - modify retry budgets
    - modify guardrails
    - infer customer intent
    - establish causal relationships
    """

    sample_size = len(historical_cases)

    dimensions = {
        "failure_category": bool(
            failure_category_learning.get("sample_size", 0)
        ),
        "amount_band": bool(
            amount_band_learning.get("sample_size", 0)
        ),
        "customer_behavior": bool(
            customer_behavior.get("sample_size", 0)
        ),
        "recency": bool(
            recency_learning.get("dated_sample_size", 0)
        ),
        "outcome_history": any(
            getattr(case, "outcome", None) in {
                "recovered",
                "in_progress",
                "failed",
                "exhausted",
                "blocked",
            }
            for case in historical_cases
        ),
    }

    available_dimensions = sum(
        1 for value in dimensions.values()
        if value
    )

    if sample_size <= 0:
        overall_quality = "insufficient"
    elif sample_size <= 2:
        overall_quality = "limited"
    elif sample_size <= 9 or available_dimensions <= 1:
        overall_quality = "moderate"
    else:
        overall_quality = "strong"

    if overall_quality == "strong" and available_dimensions >= 3:
        confidence_signal = "high"
    elif overall_quality in {"strong", "moderate"} and available_dimensions >= 2:
        confidence_signal = "moderate"
    elif overall_quality == "limited":
        confidence_signal = "low"
    else:
        confidence_signal = "insufficient"

    return {
        "available": sample_size > 0,
        "sample_size": sample_size,
        "available_dimensions": available_dimensions,
        "dimensions": dimensions,
        "overall_evidence_quality": overall_quality,
        "confidence_signal": confidence_signal,
        "interpretation": (
            "historical evidence quality only; "
            "not confidence in a financial decision"
        ),
        "provenance": {
            "attribution": "historical_evidence_synthesis",
            "episode_granularity": "invoice",
            "financial_authority": "deterministic_policy",
        },
        "advisory_only": True,
    }


def _build_historical_evidence_consistency(
    failure_category_learning: dict[str, Any],
    customer_behavior: dict[str, Any],
    amount_band_learning: dict[str, Any],
    recency_learning: dict[str, Any],
    historical_evidence_summary: dict[str, Any],
) -> dict[str, Any]:
    """Summarize directional consistency/conflict across historical evidence.

    Advisory evidence only.

    This function does not choose actions, establish financial rules,
    authorize execution, or override deterministic policy.
    """

    signals: dict[str, str] = {}

    # Failure-category learning signal.
    category_signal = failure_category_learning.get(
        "learning_signal"
    )

    if category_signal in {
        "historically_favorable",
        "historically_unfavorable",
        "historically_mixed",
    }:
        signals["failure_category"] = category_signal

    # Customer behavioral signal.
    customer_signal = customer_behavior.get(
        "behavior_signal"
    )

    if customer_signal in {
        "historically_favorable",
        "historically_unfavorable",
        "historically_mixed",
    }:
        signals["customer_behavior"] = customer_signal

    # Amount-band recovery evidence.
    # The amount band itself is never treated as inherently favorable
    # or unfavorable; only supplied historical recovery evidence is used.
    amount_rate = amount_band_learning.get(
        "recovery_rate"
    )

    if isinstance(amount_rate, (int, float)):
        if amount_rate >= 0.70:
            signals["amount_band"] = "historically_favorable"
        elif amount_rate <= 0.30:
            signals["amount_band"] = "historically_unfavorable"
        else:
            signals["amount_band"] = "historically_mixed"

    # Recency signal.
    recency_signal = recency_learning.get(
        "recency_signal"
    )

    if recency_signal in {
        "recently_favorable",
        "recently_unfavorable",
        "recently_mixed",
    }:
        signals["recency"] = recency_signal

    favorable = sum(
        1
        for signal in signals.values()
        if signal in {
            "historically_favorable",
            "recently_favorable",
        }
    )

    unfavorable = sum(
        1
        for signal in signals.values()
        if signal in {
            "historically_unfavorable",
            "recently_unfavorable",
        }
    )

    mixed = sum(
        1
        for signal in signals.values()
        if signal in {
            "historically_mixed",
            "recently_mixed",
        }
    )

    available_dimensions = {
        "failure_category": "failure_category" in signals,
        "customer_behavior": "customer_behavior" in signals,
        "amount_band": "amount_band" in signals,
        "recency": "recency" in signals,
    }

    available_count = sum(
        1
        for value in available_dimensions.values()
        if value
    )

    conflict_detected = (
        favorable > 0
        and unfavorable > 0
    )

    if available_count == 0:
        consistency_signal = "insufficient_evidence"
        interpretation = (
            "Historical evidence is insufficient to assess directional consistency."
        )
    elif conflict_detected:
        consistency_signal = "conflicting"
        interpretation = (
            "Historical evidence contains favorable and unfavorable signals; "
            "treat the disagreement as cautionary context only."
        )
    elif mixed > 0:
        consistency_signal = "mixed"
        interpretation = (
            "Historical evidence is directionally mixed; "
            "do not infer a stronger historical pattern."
        )
    else:
        consistency_signal = "aligned"
        interpretation = (
            "Available historical evidence is directionally aligned; "
            "this remains advisory context only."
        )

    return {
        "signals": signals,
        "directional_signal_counts": {
            "favorable": favorable,
            "unfavorable": unfavorable,
            "mixed": mixed,
        },
        "available_dimensions": available_dimensions,
        "conflict_detected": conflict_detected,
        "consistency_signal": consistency_signal,
        "interpretation": interpretation,
        "provenance": {
            "attribution": "historical_evidence_consistency",
            "episode_granularity": "invoice",
            "financial_authority": "deterministic_policy",
        },
        "advisory_only": True,
    }


def build_historical_decision_context(
    invoice_id: str,
    *,
    limit: int = 20,
) -> HistoricalDecisionContext:
    """Build historical decision evidence for one invoice.

    Only completed/prior invoices are considered. The current invoice
    is explicitly excluded from the historical set.

    Historical cases are matched by failure category.
    """

    invoices = get_invoices()

    current = next(
        (
            invoice
            for invoice in invoices
            if str(invoice.get("invoice_id"))
            == str(invoice_id)
        ),
        None,
    )

    if not current:
        raise ValueError(
            f"Invoice '{invoice_id}' does not exist."
        )

    category = current.get(
        "failure_category"
    )

    candidates = [
        invoice
        for invoice in invoices
        if str(invoice.get("invoice_id"))
        != str(invoice_id)
        and invoice.get("failure_category")
        == category
    ]

    # Build the current case only for contextual similarity.
    #
    # This does NOT change the current invoice or create a decision.
    # The similarity scorer itself does not use outcome, recovered amount,
    # or AI recommendation as ranking signals.
    current_case = _build_historical_case(current)

    candidate_cases = [
        (
            invoice,
            _build_historical_case(invoice),
        )
        for invoice in candidates
    ]

    # Prefer cases that are both contextually similar and have a useful
    # terminal/evidence state. Terminal status is a tie-breaker only;
    # it is NOT part of the similarity score.
    terminal_statuses = {
        "paid",
        "cancelled",
        "expired",
    }

    candidate_cases.sort(
        key=lambda item: (
            _historical_similarity_score(
                current_case,
                item[1],
            ),
            item[0].get("status")
            not in terminal_statuses,
            str(
                item[0].get("updated_at")
                or item[0].get("created_at")
                or ""
            ),
        ),
        reverse=True,
    )

    candidate_cases = candidate_cases[
        :max(1, int(limit))
    ]

    historical_cases = [
        case
        for _, case in candidate_cases
    ]

    action_statistics = (
        _build_action_statistics(
            historical_cases
        )
    )

    ai_statistics = _build_ai_statistics(
        historical_cases
    )

    ai_action_statistics = _build_ai_action_statistics(
        historical_cases
    )

    outcome_statistics = (
        _build_outcome_statistics(
            historical_cases
        )
    )

    learning_signal = _build_learning_signal(
        historical_cases
    )

    failure_category_learning = _build_failure_category_learning(
        category,
        historical_cases,
    )

    amount_band_learning = _build_amount_band_learning(
        current_amount=int(
            current.get("amount") or 0
        ),
        historical_cases=historical_cases,
    )

    customer_behavior = _build_customer_behavior(
        current_invoice=current,
        invoices=invoices,
    )


    recency_learning = _build_recency_learning(
        historical_cases,
    )


    historical_evidence_summary = _build_historical_evidence_summary(
        historical_cases=historical_cases,
        failure_category_learning=failure_category_learning,
        customer_behavior=customer_behavior,
        amount_band_learning=amount_band_learning,
        recency_learning=recency_learning,
    )


    historical_evidence_consistency = _build_historical_evidence_consistency(
        failure_category_learning=failure_category_learning,
        customer_behavior=customer_behavior,
        amount_band_learning=amount_band_learning,
        recency_learning=recency_learning,
        historical_evidence_summary=historical_evidence_summary,
        historical_evidence_consistency=historical_evidence_consistency,
    )

    return HistoricalDecisionContext(
        current_invoice_id=str(invoice_id),
        failure_category=category,
        similar_case_count=len(
            historical_cases
        ),
        historical_cases=[
            case.to_dict()
            for case in historical_cases
        ],
        action_statistics=action_statistics,
        ai_statistics=ai_statistics,
        ai_action_statistics=ai_action_statistics,
        outcome_statistics=outcome_statistics,
        learning_signal=learning_signal,
        failure_category_learning=failure_category_learning,
        amount_band_learning=amount_band_learning,
        customer_behavior=customer_behavior,
        recency_learning=recency_learning,
        historical_evidence_summary=historical_evidence_summary,
    )


def get_historical_decision_context_dict(
    invoice_id: str,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Return historical decision context as a plain dictionary."""

    return build_historical_decision_context(
        invoice_id,
        limit=limit,
    ).to_dict()


if __name__ == "__main__":
    from backend.data.db import get_invoices

    invoices = get_invoices()

    if not invoices:
        print("No invoices found.")
        raise SystemExit(1)

    target = next(
        (
            invoice
            for invoice in invoices
            if invoice.get("status") == "issued"
            and invoice.get("failure_category")
        ),
        invoices[0],
    )

    context = build_historical_decision_context(
        target["invoice_id"]
    )

    print(
        json.dumps(
            context.to_dict(),
            indent=2,
            default=str,
        )
    )
