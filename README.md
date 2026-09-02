# DunnFlow Project Track

## 1. Project Objective
DunnFlow is a financial recovery workflow for subscription payment failures, with Razorpay integration, payment-attempt tracking, recovery execution, and revenue/lifecycle event tracking.

## 2. Current Architecture
- backend/data/db.py: database access and state updates
- backend/integrations/razorpay_adapter.py: Razorpay communication and payment normalization
- backend/integrations/razorpay_ingestion.py: imports normalized Razorpay payments into DunnFlow
- backend/modules/execution.py: recovery execution and financial state transitions

## 3. Important Database Tables
### invoices
Tracks invoice lifecycle. Important fields: invoice_id, batch_id, subscription_id, razorpay_invoice_id, amount, currency, status, paid_at, due_at, failure_category, updated_at.

### subscriptions
Tracks subscription lifecycle. Important fields: subscription_id, batch_id, razorpay_subscription_id, customer_id, amount, currency, status, current_cycle, total_cycles, retry_count, last_failure_category, updated_at.

### payment_attempts
Tracks every payment attempt. Fields include attempt_id, batch_id, invoice_id, subscription_id, razorpay_payment_id, attempt_number, attempt_type, action_type, scheduled_for, executed_at, result, raw_error_code, failure_reason, gateway_status, result_detail, created_at.

### revenue_events
Financial/lifecycle event ledger. Fields include event_id, batch_id, subscription_id, invoice_id, payment_attempt_id, event_type, amount, razorpay_event_id, event_timestamp, detail.

## 4. Important DB Functions
- get_invoice(invoice_id)
- get_subscription(subscription_id)
- update_invoice_status(invoice_id, status, paid_at=None, failure_category=None)
- update_subscription_status(subscription_id, status, retry_count=None, last_failure_category=None)
- create_payment_attempt(...)
- record_revenue_event(event)

## 5. Razorpay Ingestion Rules
RazorpayIngestion accepts an optional RazorpayAdapter through its constructor.

Invoice mapping order:
1. Explicit local invoice_id
2. Razorpay invoice ID
3. notes.dunnflow_invoice_id

Payments without a valid DunnFlow invoice mapping must be skipped safely.

The local DunnFlow invoice determines the authoritative batch_id.

## 6. Successful Payment Financial Chain
For a Razorpay payment with status captured:

Razorpay captured
-> invoice becomes paid
-> subscription becomes active
-> payment_captured event
-> invoice_paid event
-> recovery_confirmed event

The successful branch currently calls update_invoice_status(), update_subscription_status(), and records the three revenue events.

## 7. Failed Payment Behavior
Failed Razorpay payments create payment-attempt records and revenue-at-risk events. Diagnosis and recovery decisions remain outside the ingestion module.

## 8. Current Changes
- Added update_invoice_status import to razorpay_ingestion.py.
- Added update_subscription_status import to razorpay_ingestion.py.
- Added successful captured-payment branch to ingest_payment().
- Successful payments now settle the DunnFlow invoice.
- Successful payments activate the associated subscription.
- Successful payments record payment_captured, invoice_paid, and recovery_confirmed events.
- Removed the overly broad success-event guard from the successful branch.
- razorpay_ingestion.py passes py_compile after these changes.

## 9. Current Test Case
Invoice: inv_phasef_003
Subscription: sub_phasef_003
Batch: phase_f_002
Amount: 29900 INR
Invoice status before test: issued
Subscription status before test: pending
Retry count: 1
Latest recovery attempt: failed
Failure category: insufficient_funds

This invoice is being used to test the successful Razorpay ingestion path.

## 10. Current Status
DONE: database schema inspection
DONE: DB update functions inspected
DONE: Razorpay payment normalization inspected
DONE: invoice mapping logic inspected
DONE: successful ingestion branch implemented
DONE: Python syntax validation
DONE: end-to-end synthetic captured-payment ingestion test
DONE: invoice/subscription/payment-attempt/revenue-event persistence verification
DONE: successful-payment idempotency verification
NEXT: test remaining Razorpay ingestion edge cases

## 11. Project Discipline
Do not repeatedly inspect files or schemas that have already been established in this track. Only inspect again when a new error or changed requirement makes it necessary.
Prefer short Windows CMD commands for modifications. Avoid fragile long triple-quoted CMD commands.
After meaningful changes, run py_compile and then perform a focused database/application test.
Keep this README updated whenever an important requirement, architectural decision, bug, fix, or test result is established.
