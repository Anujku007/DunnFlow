"""
Razorpay test-mode API wrapper for DunnFlow.

Wraps the actual Razorpay Python SDK calls needed for this project:
  - retrying a failed payment (re-attempting a charge in test mode)
  - "sending" a recovery message (update-card link) — simulated, since
    actual SMS/email/WhatsApp dispatch is out of scope for the buildathon
    and would need a real messaging provider account.

IMPORTANT: This file expects RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET (test-mode
keys) to be set as environment variables. If they aren't set, functions fall
back to a clearly-labeled simulation mode so the pipeline can still run and
be demoed without live credentials wired up yet.
"""

import os
import random
import time

try:
    import razorpay
except ImportError:
    razorpay = None

KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")

_client = None
if razorpay and KEY_ID and KEY_SECRET:
    _client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))


def _live_client_available() -> bool:
    return _client is not None


def retry_payment_test_mode(payment: dict) -> dict:
    """
    Attempt to retry a failed payment.

    Real mode: would call something like client.payment.capture() or
    re-initiate a charge against a saved token/customer via the Orders/
    Payments API, depending on how the original subscription was set up.

    Simulated mode (default, no keys configured): probabilistically returns
    captured/failed so the pipeline is fully demoable end-to-end without
    live credentials. Failure categories bias the odds the way they would
    realistically behave (e.g. a bank timeout retry is more likely to
    succeed than a genuinely insufficient-funds retry attempted too soon).
    """
    if _live_client_available():
        try:
            # Placeholder for real integration — exact call depends on how
            # the subscription/mandate was originally created. Documented
            # here so it's a clear extension point, not a false claim of
            # full production wiring.
            # result = _client.payment.capture(payment["payment_id"], {...})
            raise NotImplementedError("Live retry call not wired up yet.")
        except Exception as e:
            return {"status": "failed", "message": f"Live API error: {e}"}

    # --- Simulated test-mode behavior ---
    category = payment.get("failure_category")
    success_odds = {
        "bank_timeout": 0.75,       # transient issue, retry usually works
        "insufficient_funds": 0.5,  # coin-flip-ish, depends on payday timing
    }.get(category, 0.4)

    time.sleep(0.05)  # tiny delay to make batch runs feel "real" in a live demo
    if random.random() < success_odds:
        return {"status": "captured", "message": "Payment captured on retry (simulated)."}
    return {"status": "failed", "message": "Retry failed again (simulated)."}


def send_recovery_message(payment: dict) -> dict:
    """
    Simulate sending a recovery message (e.g. "your card has expired, update
    it here: <payment link>") to the customer.

    In a full production build this would call an SMS/email/WhatsApp provider.
    For the buildathon demo, we simulate a successful dispatch and log exactly
    what would have been sent, so the audit trail is honest about what's real
    (the decision + logging) vs. simulated (actual delivery).
    """
    payment_link = f"https://rzp.io/i/{payment['payment_id']}"  # illustrative test-mode-style link
    message = (
        f"Hi {payment.get('customer_name', 'there')}, your card on file has "
        f"expired. Please update it here to continue your subscription: {payment_link}"
    )
    time.sleep(0.05)
    return {"status": "sent", "message": f"(Simulated) Message dispatched: {message}"}