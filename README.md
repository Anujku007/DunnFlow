DunnFlow

AI-Driven Subscription Revenue Recovery Agent

DunnFlow is a revenue-recovery system built for the Razorpay AI Buildathon — Track 03: AI Revenue Recovery.

Track 03 goal: Find revenue that is slipping away and win it back.

DunnFlow detects revenue at risk, diagnoses why a payment is failing, decides on a bounded intervention, executes the recovery workflow, verifies the real payment outcome through Razorpay webhooks, and measures the recovered money.

Current Project Status

Date: September 2, 2026
Buildathon: Razorpay AI Buildathon
Track: Track 03 — AI Revenue Recovery
Current Phase: Phase 1 — Real Razorpay lifecycle
Overall state: Phase 1 webhook/recovery foundation is substantially complete; moving toward the full AI-agent automation and demo layer.

Phase 1 checklist

Razorpay connectivity

Webhook signature verification

payment.failed

payment.captured

payment.authorized

order.paid

Failed → captured lifecycle

Duplicate webhook / event-id idempotency

Out-of-order webhook handling

Payment downtime / gateway failure handling

Real Razorpay Test Mode recovery

Real payment → webhook → invoice paid → measured recovery

1. Product Concept

DunnFlow is designed around this recovery loop:

Revenue at Risk
      ↓
Detection
      ↓
Diagnosis
      ↓
AI Recovery Decision
      ↓
Guardrails
      ↓
Bounded Execution
      ↓
Customer Payment
      ↓
Razorpay Webhook
      ↓
Payment Verification
      ↓
Invoice / Subscription Recovery
      ↓
Measured ₹ Recovered
      ↓
Audit Trail

The key principle is:

DunnFlow does not count an attempted intervention as recovered revenue. Revenue is recovered only after a successful payment outcome is verified.

2. Architecture

                         ┌──────────────────────┐
                         │      Razorpay        │
                         │   Test Mode Gateway  │
                         └──────────┬───────────┘
                                    │
                         payment.* / order.paid
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   Webhook API        │
                         │ /api/webhooks/...    │
                         └──────────┬───────────┘
                                    │
                         Signature verification
                         Event-ID idempotency
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ Webhook Handler      │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ Razorpay Ingestion   │
                         │ + reconciliation     │
                         └──────────┬───────────┘
                                    │
                                    ▼
        ┌─────────────────────────────────────────────────┐
        │                 DunnFlow Engine                 │
        │                                                 │
        │ Detection → Diagnosis → Decision → Scheduler  │
        │                         ↓                       │
        │                    Execution                   │
        │                         ↓                       │
        │                    Metrics                     │
        └───────────────────────┬─────────────────────────┘
                                │
                                ▼
                         ┌───────────────┐
                         │ SQLite / DB   │
                         │ invoices      │
                         │ attempts      │
                         │ actions       │
                         │ events        │
                         │ audit trail   │
                         └───────────────┘

3. Razorpay Integration

DunnFlow uses a dedicated Razorpay client layer.

Integration responsibilities

backend/integrations/razorpay_client.py

Razorpay credential loading

Test/Live mode configuration

Razorpay Orders API

Payment communication

Razorpay-specific API error handling

Response normalization

DunnFlow's business modules do not directly communicate with Razorpay APIs.

Test Mode execution

The current real execution mode is:

DUNNFLOW_EXECUTION_MODE=razorpay_test_mode

DunnFlow creates real Razorpay Test Mode Orders and attaches the resulting order_id to the corresponding DunnFlow invoice.

This gives the system a real:

DunnFlow invoice
      ↕
Razorpay order
      ↕
Razorpay payment

correlation.

4. Real Razorpay Payment Lifecycle

The implemented lifecycle supports:

payment.authorized
        ↓
payment.captured
        ↓
order.paid

and failed payment events:

payment.failed

DunnFlow also handles a payment becoming captured after a failed state.

Important behavior

order.paid is treated as a paid-order lifecycle event and is reconciled into DunnFlow's payment/invoice state.

Successful capture results in:

payment attempt → succeeded
invoice → paid
subscription → active
recovery_confirmed event

5. Webhook Security

DunnFlow validates Razorpay webhooks using:

HMAC-SHA256

The signature is calculated against the raw request body before JSON parsing.

The webhook endpoint:

POST /api/webhooks/razorpay

uses:

x-razorpay-signature

for verification.

Invalid signatures are rejected.

A separate webhook secret is used through:

RAZORPAY_WEBHOOK_SECRET

Secrets are not stored in source code.

6. Webhook Idempotency

Razorpay webhooks can be delivered more than once.

DunnFlow now persists Razorpay event IDs in:

razorpay_webhook_events

with:

event_id PRIMARY KEY
event_type
received_at

The handler checks whether an event ID has already been processed.

Verified behavior:

First delivery:
200
status = processed

Second delivery with same event ID:
200
status = duplicate

This prevents duplicate processing of the same Razorpay webhook event.

7. Out-of-Order Webhooks

Webhook ordering cannot be assumed.

DunnFlow now uses monotonic payment-state handling:

failed     = 0
authorized = 1
captured   = 2

A later event cannot downgrade a payment that has already reached a higher state.

Verified case:

payment.captured
      ↓
late payment.authorized

The late authorized event was processed without downgrading the stored payment state.

Final verified state:

gateway_status = captured
result = succeeded
invoice = paid
subscription = active

8. Real Razorpay Recovery Flow

The clean end-to-end proof currently uses:

Batch:
benchmark_60_subscription_failures

Invoice:
inv_dunnflow_001

Recovery Action:
792

Payment Attempt:
717

Razorpay Order:
order_TX5KUfIQvYN0lU

Razorpay Payment:
pay_TX5Zhxz2SqH31x

Amount:
₹299

Flow:

Revenue at risk
      ↓
DunnFlow recovery action
      ↓
Razorpay Test Mode order
      ↓
Razorpay Checkout
      ↓
Customer/test payment succeeds
      ↓
payment.captured webhook
      ↓
DunnFlow reconciliation
      ↓
invoice marked paid
      ↓
subscription activated
      ↓
recovery_confirmed
      ↓
₹299 measured as recovered

Verified state:

invoice status       = paid
payment result       = succeeded
gateway status       = captured
subscription status  = active

Revenue events:

payment_captured
invoice_paid
recovery_confirmed

9. Measured Recovery

Before the clean real Razorpay recovery:

Recovered count:       30
Amount recovered:      ₹31,77,000
Recovery rate:         49.8%

After the verified ₹299 recovery:

Recovered count:       31
Amount recovered:      ₹32,06,900
Recovery rate:         50.2%
In progress:           15
Active:                31
Pending:               26

This is important Track 03 proof because the system demonstrates measured money recovered, not merely an attempted action.

10. Payment Downtime / Gateway Failure

DunnFlow now handles a transient Razorpay API failure safely.

The behavior is:

Razorpay API unavailable
        ↓
catch RazorpayAPIError
        ↓
NO payment attempt created
        ↓
recovery action remains planned
        ↓
retry scheduled +30 minutes
        ↓
guardrail_hit =
razorpay_gateway_unavailable
        ↓
audit entry recorded
        ↓
retry_scheduled returned

Controlled test

Test action:

Action: 780
Invoice: inv_dunnflow_013
Amount: ₹999

The Razorpay client was deliberately made to raise:

CONTROLLED TEST:
Razorpay gateway unavailable / timeout

Result:

result = retry_scheduled
status = planned
attempt_id = None
razorpay_order_id = None
recovered = False
amount_recovered = 0

Database verification:

status = planned
guardrail_hit = razorpay_gateway_unavailable
payment attempt #3 = none

Audit trail recorded:

stage = execute
result = retry_scheduled
guardrail_hit = razorpay_gateway_unavailable
payment_attempt_id = None

The retry was rescheduled 30 minutes later.

This demonstrates that DunnFlow does not manufacture a payment attempt when the gateway is unavailable.

11. Backend Structure

backend/
├── api.py
├── data/
│   ├── db.py
│   └── schema.sql
├── integrations/
│   ├── razorpay_client.py
│   └── razorpay_ingestion.py
├── modules/
│   ├── detection.py
│   ├── diagnosis.py
│   ├── decision.py
│   ├── execution.py
│   ├── scheduler.py
│   └── ...
└── webhooks/
    ├── handler.py
    └── verifier.py

Frontend:

templates/
└── index.html

static/js/
├── api.js
├── navigation.js
├── audit-trail.js
├── live-feed.js
├── metrics.js
└── scenario-cards.js

12. API Endpoints

GET  /
GET  /api/health

POST /api/webhooks/razorpay

GET  /api/batches/{batch_id}

POST /api/batches/{batch_id}/detect
POST /api/batches/{batch_id}/decide
POST /api/batches/{batch_id}/execute

GET  /api/batches/{batch_id}/metrics
GET  /api/batches/{batch_id}/report

GET  /api/batches/{batch_id}/razorpay-checkout

13. Execution Model

DunnFlow supports synthetic execution for deterministic benchmarking and Razorpay Test Mode execution for real payment lifecycle validation.

synthetic_test_mode
        OR
razorpay_test_mode

The Razorpay Test Mode path creates an actual Razorpay Test Mode Order and waits for customer/test payment completion.

It does not count order creation itself as recovered revenue.

14. Database Concepts

Invoices

Tracks:

invoice amount

invoice status

failure category

Razorpay order ID

paid timestamp

Payment Attempts

Tracks:

attempt number

attempt type

Razorpay payment ID

result

gateway status

failure information

execution timestamps

Recovery Actions

Tracks:

action type

reason

priority

scheduled time

execution state

guardrail hit

Revenue Events

Tracks concrete financial lifecycle events:

payment_captured
invoice_paid
recovery_confirmed
revenue_at_risk

Audit Log

Provides an execution trail for detection, decisions, guardrails, payment actions, and failures.

15. Track 03 Alignment

DunnFlow is built around:

Detect revenue at risk
        ↓
Diagnose root cause
        ↓
Choose intervention
        ↓
Apply guardrails
        ↓
Execute bounded recovery
        ↓
Verify outcome
        ↓
Measure money recovered
        ↓
Stop / retry / escalate
        ↓
Maintain audit trail

Completed foundation:

Real Razorpay connectivity

Real Test Mode payment flow

Webhook verification

Lifecycle reconciliation

Event-ID idempotency

Out-of-order protection

Gateway downtime resilience

Measured recovered revenue

Auditability

16. Next Phase — AI Recovery Automation

The next major milestone is the AI Revenue Recovery Agent.

1. Revenue-at-risk detection

Turn the existing detection pipeline into a clear agent input.

2. AI diagnosis

Determine why revenue is at risk:

insufficient funds
temporary gateway problem
payment method problem
repeated failure
customer action required

3. AI intervention decision

Choose among bounded actions:

retry payment
delay retry
request payment-method update
customer notification
manual review
no action

4. Guardrails

Examples:

maximum automated payment retries
minimum retry interval
already-paid protection
gateway outage protection
customer-action escalation
manual-review escalation

5. Bounded execution

Execute only actions explicitly allowed by the recovery policy.

6. Recovery verification

No recovery is counted until a successful payment outcome is observed.

7. Stopping rules

Examples:

payment succeeds
retry budget exhausted
gateway unavailable
customer action required
manual review required
invoice no longer eligible

8. Escalation

Cases that cannot be safely automated should move to manual review.

9. Audit trail

Every agent decision should explain:

why this customer was selected
why this intervention was selected
which guardrails were evaluated
what was executed
what happened
how much revenue was recovered

17. Planned Final Demo

60 failed subscriptions
        ↓
DunnFlow detects revenue at risk
        ↓
AI diagnoses failure patterns
        ↓
AI prioritizes recovery opportunities
        ↓
Guardrails select safe actions
        ↓
DunnFlow creates Razorpay recovery orders
        ↓
Customer completes payment
        ↓
Razorpay webhook arrives
        ↓
DunnFlow verifies + reconciles
        ↓
Invoice becomes paid
        ↓
Subscription becomes active
        ↓
₹ recovered increases
        ↓
Dashboard shows measurable result

Resilience case:

Razorpay unavailable
        ↓
DunnFlow does NOT fabricate recovery
        ↓
retry scheduled
        ↓
guardrail + audit trail

18. Development Rules

Preserve the existing architecture.

Make small, checkpointed changes.

Prefer terminal-driven changes.

Compile/test after each change.

Never expose Razorpay secrets.

Do not count attempted actions as recovered revenue.

Use real Razorpay Test Mode for payment lifecycle proof.

Keep webhook processing idempotent.

Never assume webhook ordering.

Keep recovery execution bounded and auditable.

19. Current Checkpoint

Phase 1 — Real Razorpay lifecycle: COMPLETE ✅

Most important verified proof:

DunnFlow recovery
      ↓
Real Razorpay Test Mode Order
      ↓
Checkout payment
      ↓
payment.captured webhook
      ↓
Invoice paid
      ↓
Subscription active
      ↓
recovery_confirmed
      ↓
₹299 measured recovery

Resilience proof:

Razorpay API outage
      ↓
No fake payment attempt
      ↓
Action remains planned
      ↓
30-minute retry
      ↓
Guardrail + audit trail

Immediate next milestone

Build the AI-driven detection → diagnosis → decision → guarded execution loop on top of the now-proven Razorpay lifecycle.

Repository

GitHub: https://github.com/Anujku007/DunnFlow

Status Summary

Capability

Status

Razorpay connectivity

✅

Test Mode Orders

✅

Webhook signature verification

✅

payment.failed

✅

payment.authorized

✅

payment.captured

✅

order.paid

✅

Failed → Captured lifecycle

✅

Event-ID idempotency

✅

Out-of-order handling

✅

Gateway downtime handling

✅

Real Razorpay recovery

✅

Measured recovered revenue

✅

Audit trail

✅

AI diagnosis

🔄 Next

AI intervention decision

🔄 Next

Automated bounded recovery agent

🔄 Next

Escalation/stopping policy

🔄 Next

Final dashboard/polish

⏳

Architecture/pitch/demo

⏳

Buildathon submission

⏳