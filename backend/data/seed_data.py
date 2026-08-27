"""
Synthetic failed-subscription-payment generator for DunnFlow.

Uses Razorpay's real documented test-mode decline reason codes
(https://razorpay.com/docs/payments/payments/test-card-details/)
so the "raw_error_code" values in our data look exactly like what
you'd get back from the actual test-mode API when a test card fails.

Reference decline reasons used:
  - insufficient_fund      -> customer's bank balance too low
  - payment_timed_out      -> bank/gateway took too long, treated like a
                               transient bank-side issue (maps to bank_timeout)
  - authentication_failed  -> OTP/verification failed
  - card_expired           -> not an official Razorpay test-card reason code,
                               but a very common real-world dunning cause, so
                               we include it to keep the demo's problem space
                               realistic (clearly commented as synthetic).
"""

import random
import string
from datetime import datetime, timedelta, timezone

from backend.data.db import upsert_payment, init_db

RAW_REASONS = [
    # (raw_error_code, human failure_reason)          weight
    ("insufficient_fund", "Insufficient balance in customer's account"),
    ("payment_timed_out", "Payment gateway/bank timed out during processing"),
    ("authentication_failed", "OTP/verification failed during authentication"),
    ("card_expired", "Card has expired"),
]
WEIGHTS = [0.4, 0.25, 0.15, 0.2]  # insufficient funds most common, matches real-world dunning data

FIRST_NAMES = ["Aarav", "Vivaan", "Ishaan", "Diya", "Ananya", "Kabir", "Meera",
               "Rohan", "Sanya", "Aditya", "Priya", "Karan", "Neha", "Farhan",
               "Zoya", "Arjun", "Tanvi", "Yash", "Riya", "Sarthak"]
LAST_NAMES = ["Sharma", "Verma", "Iyer", "Patel", "Reddy", "Nair", "Gupta",
              "Khan", "Chatterjee", "Menon", "Rao", "Singh", "Das", "Joshi"]

PLAN_AMOUNTS_PAISE = [29900, 49900, 99900, 149900, 199900]  # ₹299 / ₹499 / ₹999 / ₹1499 / ₹1999


def _random_id(prefix: str, length: int = 14) -> str:
    chars = string.ascii_letters + string.digits
    return f"{prefix}_{''.join(random.choices(chars, k=length))}"


def _random_customer():
    name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
    email_local = name.lower().replace(" ", ".")
    return name, f"{email_local}{random.randint(1,999)}@example.com"


def _random_timestamp(days_back: int = 10) -> str:
    now = datetime.now(timezone.utc)
    delta = timedelta(
        days=random.randint(0, days_back),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )
    return (now - delta).isoformat(timespec="seconds")


def generate_failed_payment() -> dict:
    raw_error_code, failure_reason = random.choices(RAW_REASONS, weights=WEIGHTS, k=1)[0]
    customer_id = _random_id("cust", 10)
    name, email = _random_customer()

    return {
        "payment_id": _random_id("pay"),
        "customer_id": customer_id,
        "customer_name": name,
        "customer_email": email,
        "amount": random.choice(PLAN_AMOUNTS_PAISE),
        "currency": "INR",
        "raw_error_code": raw_error_code,
        "failure_reason": failure_reason,
        "failure_category": None,      # filled in later by diagnosis.py
        "status": "failed",
        "retry_count": 0,
        "last_attempt_at": None,
        "created_at": _random_timestamp(),
    }


def seed(n: int = 60, reset: bool = False):
    """Generate n synthetic failed payments and insert into the DB.

    reset=True wipes existing payment rows first (useful for repeatable demos).
    """
    init_db()

    if reset:
        from backend.data.db import get_conn
        with get_conn() as conn:
            conn.execute("DELETE FROM audit_log")
            conn.execute("DELETE FROM retry_attempts")
            conn.execute("DELETE FROM payments")

    for _ in range(n):
        upsert_payment(generate_failed_payment())

    print(f"Seeded {n} synthetic failed payments into the database.")


if __name__ == "__main__":
    seed(n=60, reset=True)