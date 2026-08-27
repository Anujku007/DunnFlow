"""
DunnFlow deterministic benchmark generator.

This creates the synthetic benchmark used to evaluate the complete
subscription-revenue-recovery pipeline.

IMPORTANT
---------
These are SYNTHETIC benchmark records.

They are designed to mirror the important Razorpay Subscription recovery
concepts used by DunnFlow:

    subscription
        -> invoice
        -> failed payment attempt
        -> recovery decision
        -> recovery attempt
        -> verified revenue outcome

They are NOT real Razorpay transactions.

Why deterministic?
------------------
A hackathon demo needs reproducible evidence. Running the same benchmark
twice should start from the same state and produce comparable results.

Benchmark size:
    60 subscriptions
    60 invoices
    60 initial failed payment attempts

Failure distribution:
    15 insufficient_funds
    15 bank_timeout
    12 auth_failed
    12 card_expired
     6 unclassified

Intentional benchmark behavior
-------------------------------

1. Bank timeout
   Most cases recover on the first DunnFlow retry.

2. Insufficient funds
   Some recover after another retry.
   Some deliberately exhaust the automated retry budget.

3. Authentication failure
   Customer action is required.
   No automatic payment retry is performed.

4. Card expired
   Payment-method update is required.
   No blind payment retry is performed.

5. Unclassified
   No automated recovery is allowed.
   These cases go to manual review.

6. Guardrail cases
   A small number contain a recent previous retry so the decision engine
   must block another attempt because the minimum retry gap has not elapsed.

The benchmark therefore contains:
    - successful recovery opportunities
    - in-progress/customer-action cases
    - exhausted cases
    - manual-review cases
    - guardrail-blocked cases

The goal is NOT to maximize recovery percentage artificially.

The goal is to test whether DunnFlow makes the correct bounded decision.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.data.db import (
    clear_all_data,
    create_batch_run,
    create_payment_attempt,
    init_db,
    record_revenue_event,
    update_batch_run,
    upsert_invoice,
    upsert_subscription,
)


# ===========================================================================
# BENCHMARK CONFIGURATION
# ===========================================================================

BENCHMARK_SIZE = 60

BATCH_ID = "benchmark_60_subscription_failures"


# ===========================================================================
# CUSTOMER / PLAN DATA
# ===========================================================================

PLAN_DEFINITIONS = [
    {
        "plan_id": "plan_dunnflow_basic",
        "plan_name": "DunnFlow Basic",
        "amount": 29900,
    },
    {
        "plan_id": "plan_dunnflow_growth",
        "plan_name": "DunnFlow Growth",
        "amount": 49900,
    },
    {
        "plan_id": "plan_dunnflow_pro",
        "plan_name": "DunnFlow Pro",
        "amount": 99900,
    },
    {
        "plan_id": "plan_dunnflow_business",
        "plan_name": "DunnFlow Business",
        "amount": 149900,
    },
    {
        "plan_id": "plan_dunnflow_scale",
        "plan_name": "DunnFlow Scale",
        "amount": 199900,
    },
]


CUSTOMERS = [
    ("Aarav", "Sharma"),
    ("Vivaan", "Verma"),
    ("Ishaan", "Iyer"),
    ("Diya", "Patel"),
    ("Ananya", "Reddy"),
    ("Kabir", "Nair"),
    ("Meera", "Gupta"),
    ("Rohan", "Khan"),
    ("Sanya", "Menon"),
    ("Aditya", "Rao"),
    ("Priya", "Singh"),
    ("Karan", "Das"),
    ("Neha", "Joshi"),
    ("Farhan", "Chatterjee"),
    ("Zoya", "Nair"),
    ("Arjun", "Patel"),
    ("Tanvi", "Sharma"),
    ("Yash", "Gupta"),
    ("Riya", "Verma"),
    ("Sarthak", "Reddy"),
]


# ===========================================================================
# FAILURE DEFINITIONS
# ===========================================================================

FAILURE_SCENARIOS = {
    "insufficient_funds": {
        "raw_error_code": "insufficient_fund",
        "failure_reason": (
            "Customer's bank account has insufficient available balance."
        ),
    },
    "bank_timeout": {
        "raw_error_code": "payment_timed_out",
        "failure_reason": (
            "Bank or payment gateway did not respond within the allowed time."
        ),
    },
    "auth_failed": {
        "raw_error_code": "authentication_failed",
        "failure_reason": (
            "Customer authentication or OTP verification failed."
        ),
    },
    "card_expired": {
        "raw_error_code": "card_expired",
        "failure_reason": (
            "Payment method associated with the subscription has expired."
        ),
    },
    "unclassified": {
        "raw_error_code": "unknown_gateway_error",
        "failure_reason": (
            "Gateway returned an error that DunnFlow does not recognize."
        ),
    },
}


# Exact deterministic failure distribution.
SCENARIO_SEQUENCE = (
    ["insufficient_funds"] * 15
    + ["bank_timeout"] * 15
    + ["auth_failed"] * 12
    + ["card_expired"] * 12
    + ["unclassified"] * 6
)


# ===========================================================================
# SPECIAL BENCHMARK CASES
# ===========================================================================

"""
Case numbering uses 1-based subscription numbers.

The benchmark deliberately gives several insufficient-funds cases different
starting states so we can demonstrate:

    recover
    exhaust
    guardrail block

Bank-timeout cases are simpler:

    first recovery retry succeeds

Customer-action categories remain awaiting_customer.

Unknown failures remain manual review.
"""


# Insufficient-funds cases that should exhaust after the next attempt.

INSUFFICIENT_EXHAUST_CASES = {
    9,
    10,
    11,
}

INSUFFICIENT_GUARDRAIL_CASES = {
    12,
    13,
    14,
    15,
}


# The remaining insufficient-funds cases are normal recovery candidates.

#   23-30 => recover after another retry


# ===========================================================================
# TIME HELPERS
# ===========================================================================

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


# ===========================================================================
# DETERMINISTIC CUSTOMER / PLAN HELPERS
# ===========================================================================

def _customer(index: int) -> tuple[str, str, str]:
    first, last = CUSTOMERS[index % len(CUSTOMERS)]

    customer_id = f"cust_dunnflow_{index + 1:03d}"
    customer_name = f"{first} {last}"

    customer_email = (
        f"{first.lower()}.{last.lower()}"
        f"{index + 1:03d}@example.com"
    )

    return (
        customer_id,
        customer_name,
        customer_email,
    )


def _plan(index: int) -> dict:
    return PLAN_DEFINITIONS[
        index % len(PLAN_DEFINITIONS)
    ]


# ===========================================================================
# RECORD BUILDERS
# ===========================================================================

def build_subscription(
    *,
    index: int,
    batch_id: str,
    created_at: str,
    scenario: str,
    initial_retry_count: int = 1,
) -> dict:

    customer_id, customer_name, customer_email = _customer(index)

    plan = _plan(index)

    number = index + 1

    return {
        "subscription_id": (
            f"sub_dunnflow_{number:03d}"
        ),

        "batch_id": batch_id,

        # Synthetic Razorpay-style identifier.
        "razorpay_subscription_id": (
            f"sub_test_dunnflow_{number:03d}"
        ),

        "customer_id": customer_id,
        "customer_name": customer_name,
        "customer_email": customer_email,

        "plan_id": plan["plan_id"],
        "plan_name": plan["plan_name"],

        "amount": plan["amount"],
        "currency": "INR",

        "status": "pending",

        "current_cycle": 1,
        "total_cycles": 12,

        # 1 = the original failed charge.
        #
        # Special guardrail/exhaustion cases can have additional previous
        # recovery attempts and therefore a higher retry_count.
        "retry_count": initial_retry_count,

        "last_failure_category": scenario,

        "created_at": created_at,
        "updated_at": created_at,
    }


def build_invoice(
    *,
    index: int,
    batch_id: str,
    subscription: dict,
    created_at: str,
    scenario: str,
) -> dict:

    number = index + 1

    return {
        "invoice_id": (
            f"inv_dunnflow_{number:03d}"
        ),

        "batch_id": batch_id,

        "subscription_id": subscription[
            "subscription_id"
        ],

        # Synthetic Razorpay-style identifier.
        "razorpay_invoice_id": (
            f"inv_test_dunnflow_{number:03d}"
        ),

        "amount": subscription["amount"],
        "currency": "INR",

        # Failed recurring charge leaves the invoice unpaid.
        "status": "issued",

        "issued_at": created_at,
        "paid_at": None,

        "due_at": _iso(
            datetime.fromisoformat(created_at)
            + timedelta(days=3)
        ),

        "failure_category": scenario,

        "created_at": created_at,
        "updated_at": created_at,
    }


def build_initial_failed_attempt(
    *,
    index: int,
    batch_id: str,
    subscription: dict,
    invoice: dict,
    created_at: str,
    scenario: str,
) -> dict:

    number = index + 1

    scenario_data = FAILURE_SCENARIOS[
        scenario
    ]

    return {
        "batch_id": batch_id,

        "invoice_id": invoice[
            "invoice_id"
        ],

        "subscription_id": subscription[
            "subscription_id"
        ],

        "razorpay_payment_id": (
            f"pay_test_dunnflow_"
            f"{number:03d}_01"
        ),

        "attempt_number": 1,

        "attempt_type": "initial_charge",

        "action_type": "initial_subscription_charge",

        "scheduled_for": created_at,
        "executed_at": created_at,

        "result": "failed",

        "raw_error_code": scenario_data[
            "raw_error_code"
        ],

        "failure_reason": scenario_data[
            "failure_reason"
        ],

        "gateway_status": "failed",

        "result_detail": (
            f"Synthetic initial subscription charge failed. "
            f"Benchmark scenario={scenario}."
        ),

        "created_at": created_at,
    }


# ===========================================================================
# PREVIOUS RETRY HISTORY
# ===========================================================================

def seed_previous_retries(
    *,
    index: int,
    batch_id: str,
    subscription: dict,
    invoice: dict,
    scenario: str,
) -> int:
    """
    Seed controlled historical recovery attempts for special benchmark cases.

    Returns the number of PREVIOUS automated recovery attempts created.

    These historical attempts exist solely so that the decision engine can
    demonstrate real guardrail behavior during the benchmark.
    """

    number = index + 1

    # ---------------------------------------------------------------
    # Guardrail cases
    #
    # One recent failed retry is enough for the decision engine to
    # demonstrate the minimum-gap guardrail.
    # ---------------------------------------------------------------

    if number in INSUFFICIENT_GUARDRAIL_CASES:

        executed_at = _now() - timedelta(hours=2)

        create_payment_attempt(
            {
                "batch_id": batch_id,

                "invoice_id": invoice[
                    "invoice_id"
                ],

                "subscription_id": subscription[
                    "subscription_id"
                ],

                "razorpay_payment_id": (
                    f"pay_test_dunnflow_"
                    f"{number:03d}_02"
                ),

                "attempt_number": 2,

                "attempt_type": "recovery_payment",

                "action_type": "retry_payment",

                "scheduled_for": _iso(
                    executed_at
                ),

                "executed_at": _iso(
                    executed_at
                ),

                "result": "failed",

                "raw_error_code": (
                    "insufficient_fund"
                ),

                "failure_reason": (
                    "Synthetic previous retry "
                    "failed before minimum gap elapsed."
                ),

                "gateway_status": "failed",

                "result_detail": (
                    "Benchmark setup: recent previous "
                    "recovery retry intentionally seeded "
                    "to test minimum-gap guardrail."
                ),

                "created_at": _iso(
                    executed_at
                ),
            }
        )

        return 1

    # ---------------------------------------------------------------
    # Exhaustion cases
    #
    # Two previous recovery retries have already failed.
    #
    # The next decision is still allowed because retry budget is 3,
    # but the synthetic gateway will fail the next attempt too.
    # That produces exhausted.
    # ---------------------------------------------------------------

    if number in INSUFFICIENT_EXHAUST_CASES:

        first_retry_time = (
            _now() - timedelta(days=3)
        )

        second_retry_time = (
            _now() - timedelta(days=2)
        )

        create_payment_attempt(
            {
                "batch_id": batch_id,
                "invoice_id": invoice[
                    "invoice_id"
                ],
                "subscription_id": subscription[
                    "subscription_id"
                ],

                "razorpay_payment_id": (
                    f"pay_test_dunnflow_"
                    f"{number:03d}_02"
                ),

                "attempt_number": 2,

                "attempt_type": "recovery_payment",

                "action_type": "retry_payment",

                "scheduled_for": _iso(
                    first_retry_time
                ),

                "executed_at": _iso(
                    first_retry_time
                ),

                "result": "failed",

                "raw_error_code": (
                    "insufficient_fund"
                ),

                "failure_reason": (
                    "Synthetic previous retry "
                    "failed due to insufficient funds."
                ),

                "gateway_status": "failed",

                "result_detail": (
                    "Benchmark setup: previous "
                    "recovery attempt #1."
                ),

                "created_at": _iso(
                    first_retry_time
                ),
            }
        )

        create_payment_attempt(
            {
                "batch_id": batch_id,
                "invoice_id": invoice[
                    "invoice_id"
                ],
                "subscription_id": subscription[
                    "subscription_id"
                ],

                "razorpay_payment_id": (
                    f"pay_test_dunnflow_"
                    f"{number:03d}_03"
                ),

                "attempt_number": 3,

                "attempt_type": "recovery_payment",

                "action_type": "retry_payment",

                "scheduled_for": _iso(
                    second_retry_time
                ),

                "executed_at": _iso(
                    second_retry_time
                ),

                "result": "failed",

                "raw_error_code": (
                    "insufficient_fund"
                ),

                "failure_reason": (
                    "Synthetic previous retry "
                    "failed due to insufficient funds."
                ),

                "gateway_status": "failed",

                "result_detail": (
                    "Benchmark setup: previous "
                    "recovery attempt #2."
                ),

                "created_at": _iso(
                    second_retry_time
                ),
            }
        )

        return 2

    return 0


# ===========================================================================
# REVENUE EVENTS
# ===========================================================================

def record_initial_revenue_events(
    *,
    batch_id: str,
    subscription: dict,
    invoice: dict,
    payment_attempt_id: int,
    created_at: str,
    scenario: str,
) -> None:

    record_revenue_event(
        {
            "batch_id": batch_id,

            "subscription_id": subscription[
                "subscription_id"
            ],

            "invoice_id": invoice[
                "invoice_id"
            ],

            "payment_attempt_id": payment_attempt_id,

            "event_type": "revenue_at_risk",

            "amount": invoice[
                "amount"
            ],

            "event_timestamp": created_at,

            "detail": (
                f"Invoice {invoice['invoice_id']} "
                f"entered recovery scope after a "
                f"failed subscription charge."
            ),
        }
    )

    record_revenue_event(
        {
            "batch_id": batch_id,

            "subscription_id": subscription[
                "subscription_id"
            ],

            "invoice_id": invoice[
                "invoice_id"
            ],

            "payment_attempt_id": payment_attempt_id,

            "event_type": "payment_failed",

            "amount": invoice[
                "amount"
            ],

            "event_timestamp": created_at,

            "detail": (
                f"Initial charge failed with "
                f"category={scenario}."
            ),
        }
    )


# ===========================================================================
# SEED
# ===========================================================================

def seed_benchmark(
    *,
    reset: bool = True,
    size: int = BENCHMARK_SIZE,
) -> str:
    """
    Create the deterministic mixed-outcome benchmark.

    Returns:
        batch_id
    """

    if size <= 0:
        raise ValueError(
            "Benchmark size must be greater than zero."
        )

    if size > len(SCENARIO_SEQUENCE):
        raise ValueError(
            f"Benchmark size cannot exceed "
            f"{len(SCENARIO_SEQUENCE)}."
        )

    init_db()

    if reset:
        clear_all_data()

    batch_id = BATCH_ID

    started_at = _iso(
        _now()
    )

    create_batch_run(
        batch_id,
        started_at=started_at,
        status="running",
    )

    total_subscriptions = 0
    total_invoices = 0
    amount_at_risk = 0

    scenario_counts: dict[str, int] = {}

    # ---------------------------------------------------------------
    # Create the benchmark cases.
    # ---------------------------------------------------------------

    for index in range(size):

        number = index + 1

        scenario = SCENARIO_SEQUENCE[
            index
        ]

        scenario_counts[scenario] = (
            scenario_counts.get(
                scenario,
                0,
            ) + 1
        )

        # Give records slightly different historical timestamps.
        created_dt = (
            _now()
            - timedelta(
                days=(size - number) // 6,
                hours=number % 6,
            )
        )

        created_at = _iso(
            created_dt
        )

        # -----------------------------------------------------------
        # Determine historical retry count.
        # -----------------------------------------------------------

        if number in INSUFFICIENT_EXHAUST_CASES:
            previous_retry_count = 2

        elif number in INSUFFICIENT_GUARDRAIL_CASES:
            previous_retry_count = 1

        else:
            previous_retry_count = 0

        # -----------------------------------------------------------
        # Subscription
        # -----------------------------------------------------------

        subscription = build_subscription(
            index=index,
            batch_id=batch_id,
            created_at=created_at,
            scenario=scenario,
            initial_retry_count=previous_retry_count,
        )

        upsert_subscription(
            subscription
        )

        # -----------------------------------------------------------
        # Invoice
        # -----------------------------------------------------------

        invoice = build_invoice(
            index=index,
            batch_id=batch_id,
            subscription=subscription,
            created_at=created_at,
            scenario=scenario,
        )

        upsert_invoice(
            invoice
        )

        # -----------------------------------------------------------
        # Original failed subscription charge
        # -----------------------------------------------------------

        initial_attempt = (
            build_initial_failed_attempt(
                index=index,
                batch_id=batch_id,
                subscription=subscription,
                invoice=invoice,
                created_at=created_at,
                scenario=scenario,
            )
        )

        attempt_id = create_payment_attempt(
            initial_attempt
        )

        # -----------------------------------------------------------
        # Special historical attempts
        # -----------------------------------------------------------

        seed_previous_retries(
            index=index,
            batch_id=batch_id,
            subscription=subscription,
            invoice=invoice,
            scenario=scenario,
        )

        # -----------------------------------------------------------
        # Financial events
        # -----------------------------------------------------------

        record_initial_revenue_events(
            batch_id=batch_id,
            subscription=subscription,
            invoice=invoice,
            payment_attempt_id=attempt_id,
            created_at=created_at,
            scenario=scenario,
        )

        total_subscriptions += 1
        total_invoices += 1

        amount_at_risk += invoice[
            "amount"
        ]

    # ---------------------------------------------------------------
    # Update batch baseline.
    # ---------------------------------------------------------------

    update_batch_run(
        batch_id,
        total_subscriptions=total_subscriptions,
        total_invoices=total_invoices,
        amount_at_risk=amount_at_risk,
        amount_recovered=0,
        recovered_count=0,
        exhausted_count=0,
        in_progress_count=0,
        manual_review_count=0,
    )

    # ---------------------------------------------------------------
    # Console report
    # ---------------------------------------------------------------

    print()
    print("=" * 68)
    print("DUNNFLOW MIXED-OUTCOME BENCHMARK SEEDED")
    print("=" * 68)

    print(
        f"Batch ID:              {batch_id}"
    )

    print(
        f"Subscriptions:         {total_subscriptions}"
    )

    print(
        f"Invoices at risk:      {total_invoices}"
    )

    print(
        f"Amount at risk:        "
        f"₹{amount_at_risk / 100:,.2f}"
    )

    print()
    print("Failure distribution:")

    for category, count in scenario_counts.items():
        print(
            f"  {category:<22} {count}"
        )

    print()
    print("Special benchmark cases:")
    print(
        f"  insufficient_funds exhaustion cases: "
        f"{len(INSUFFICIENT_EXHAUST_CASES)}"
    )
    print(
        f"  recent-retry guardrail cases:        "
        f"{len(INSUFFICIENT_GUARDRAIL_CASES)}"
    )

    print()
    print(
        "Expected behavior:"
    )
    print(
        "  bank_timeout       -> mostly recover"
    )
    print(
        "  insufficient_funds -> mix of recover/exhaust/block"
    )
    print(
        "  auth_failed        -> awaiting customer"
    )
    print(
        "  card_expired       -> payment-method update"
    )
    print(
        "  unclassified       -> manual review"
    )

    print("=" * 68)
    print()

    return batch_id


# ===========================================================================
# CLI
# ===========================================================================

if __name__ == "__main__":
    seed_benchmark(
        reset=True,
        size=60,
    )