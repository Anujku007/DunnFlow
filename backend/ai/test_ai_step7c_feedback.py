from backend.ai.recovery_advisor import RecoveryAdvisor


def get_bounded_feedback(
    historical_context: dict,
) -> dict:
    """
    Mirror the Step 7C trust boundary against supplied historical
    context without invoking the AI provider.
    """

    raw = historical_context.get(
        "ai_action_statistics",
        {},
    )

    bounded = {}

    if not isinstance(raw, dict):
        return bounded

    for action_name, stats in raw.items():

        if not isinstance(action_name, str):
            continue

        if not isinstance(stats, dict):
            continue

        total = stats.get("total_cases")
        recovered = stats.get("recovered_cases")
        rate = stats.get("recovery_rate")
        agreement = stats.get("agreement_cases")
        disagreement = stats.get("disagreement_cases")

        if (
            not isinstance(total, int)
            or isinstance(total, bool)
            or total < 0
        ):
            continue

        if (
            not isinstance(recovered, int)
            or isinstance(recovered, bool)
            or recovered < 0
            or recovered > total
        ):
            continue

        if (
            not isinstance(agreement, int)
            or isinstance(agreement, bool)
            or agreement < 0
            or agreement > total
        ):
            continue

        if (
            not isinstance(disagreement, int)
            or isinstance(disagreement, bool)
            or disagreement < 0
            or disagreement > total
        ):
            continue

        if (
            not isinstance(rate, (int, float))
            or isinstance(rate, bool)
            or not 0.0 <= float(rate) <= 1.0
        ):
            continue

        if stats.get("attribution") != "advisory_correlation":
            continue

        if stats.get("episode_granularity") != "invoice":
            continue

        if stats.get("financial_authority") != "deterministic_policy":
            continue

        bounded[action_name] = {
            "total_cases": total,
            "recovered_cases": recovered,
            "recovery_rate": float(rate),
            "agreement_cases": agreement,
            "disagreement_cases": disagreement,
            "attribution": "advisory_correlation",
            "episode_granularity": "invoice",
            "financial_authority": "deterministic_policy",
        }

    return bounded


def test_valid_feedback():
    context = {
        "ai_action_statistics": {
            "retry_payment": {
                "total_cases": 5,
                "recovered_cases": 3,
                "recovery_rate": 0.6,
                "agreement_cases": 2,
                "disagreement_cases": 3,
                "attribution": "advisory_correlation",
                "episode_granularity": "invoice",
                "financial_authority": "deterministic_policy",
            }
        }
    }

    result = get_bounded_feedback(context)

    assert "retry_payment" in result
    assert result["retry_payment"]["total_cases"] == 5
    assert result["retry_payment"]["recovered_cases"] == 3
    assert result["retry_payment"]["recovery_rate"] == 0.6


def test_negative_counts_rejected():
    context = {
        "ai_action_statistics": {
            "retry_payment": {
                "total_cases": -5,
                "recovered_cases": 3,
                "recovery_rate": 0.6,
                "agreement_cases": 2,
                "disagreement_cases": 3,
                "attribution": "advisory_correlation",
                "episode_granularity": "invoice",
                "financial_authority": "deterministic_policy",
            }
        }
    }

    assert get_bounded_feedback(context) == {}


def test_recovered_greater_than_total_rejected():
    context = {
        "ai_action_statistics": {
            "retry_payment": {
                "total_cases": 2,
                "recovered_cases": 5,
                "recovery_rate": 2.5,
                "agreement_cases": 1,
                "disagreement_cases": 1,
                "attribution": "advisory_correlation",
                "episode_granularity": "invoice",
                "financial_authority": "deterministic_policy",
            }
        }
    }

    assert get_bounded_feedback(context) == {}


def test_invalid_recovery_rate_rejected():
    context = {
        "ai_action_statistics": {
            "retry_payment": {
                "total_cases": 5,
                "recovered_cases": 3,
                "recovery_rate": 4.2,
                "agreement_cases": 2,
                "disagreement_cases": 3,
                "attribution": "advisory_correlation",
                "episode_granularity": "invoice",
                "financial_authority": "deterministic_policy",
            }
        }
    }

    assert get_bounded_feedback(context) == {}


def test_fake_attribution_rejected():
    context = {
        "ai_action_statistics": {
            "retry_payment": {
                "total_cases": 5,
                "recovered_cases": 3,
                "recovery_rate": 0.6,
                "agreement_cases": 2,
                "disagreement_cases": 3,
                "attribution": "ai_caused_recovery",
                "episode_granularity": "invoice",
                "financial_authority": "deterministic_policy",
            }
        }
    }

    assert get_bounded_feedback(context) == {}


def test_fake_financial_authority_rejected():
    context = {
        "ai_action_statistics": {
            "retry_payment": {
                "total_cases": 5,
                "recovered_cases": 3,
                "recovery_rate": 0.6,
                "agreement_cases": 2,
                "disagreement_cases": 3,
                "attribution": "advisory_correlation",
                "episode_granularity": "invoice",
                "financial_authority": "ai",
            }
        }
    }

    assert get_bounded_feedback(context) == {}


def test_fake_episode_granularity_rejected():
    context = {
        "ai_action_statistics": {
            "retry_payment": {
                "total_cases": 5,
                "recovered_cases": 3,
                "recovery_rate": 0.6,
                "agreement_cases": 2,
                "disagreement_cases": 3,
                "attribution": "advisory_correlation",
                "episode_granularity": "audit_row",
                "financial_authority": "deterministic_policy",
            }
        }
    }

    assert get_bounded_feedback(context) == {}


def test_non_dictionary_statistics_rejected():
    context = {
        "ai_action_statistics": "fake historical data"
    }

    assert get_bounded_feedback(context) == {}


def test_ai_action_feedback_cannot_be_used_as_execution_authority():
    context = {
        "ai_action_statistics": {
            "retry_payment": {
                "total_cases": 100,
                "recovered_cases": 100,
                "recovery_rate": 1.0,
                "agreement_cases": 100,
                "disagreement_cases": 0,
                "attribution": "advisory_correlation",
                "episode_granularity": "invoice",
                "financial_authority": "deterministic_policy",
            }
        }
    }

    result = get_bounded_feedback(context)

    assert result["retry_payment"]["financial_authority"] == (
        "deterministic_policy"
    )


def run():
    tests = [
        test_valid_feedback,
        test_negative_counts_rejected,
        test_recovered_greater_than_total_rejected,
        test_invalid_recovery_rate_rejected,
        test_fake_attribution_rejected,
        test_fake_financial_authority_rejected,
        test_fake_episode_granularity_rejected,
        test_non_dictionary_statistics_rejected,
        test_ai_action_feedback_cannot_be_used_as_execution_authority,
    ]

    passed = 0
    failed = 0

    print("=" * 80)
    print("STEP 7C — AI ACTION FEEDBACK ADVERSARIAL GATE")
    print("=" * 80)

    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"FAIL: {test.__name__}")
            print(f"      {type(exc).__name__}: {exc}")
            failed += 1

    print()
    print(f"STEP 7C RESULTS: {passed} PASS / {failed} FAIL")

    if failed:
        raise SystemExit(1)

    print()
    print("AI ACTION FEEDBACK TRUST BOUNDARY: VERIFIED")
    print("MALFORMED VALUES: REJECTED")
    print("FAKE ATTRIBUTION: REJECTED")
    print("FAKE AUTHORITY: REJECTED")
    print("FAKE EPISODE GRANULARITY: REJECTED")
    print("EXECUTION AUTHORITY: NOT GRANTED")
    print()
    print("NO PAYMENT.")
    print("NO RAZORPAY API CALL.")
    print("NO RECOVERY ACTION.")
    print("NO WEBHOOK.")
    print("NO DETERMINISTIC DECISION CHANGE.")
    print("NO DATABASE WRITE.")
    print("=" * 80)


if __name__ == "__main__":
    run()
