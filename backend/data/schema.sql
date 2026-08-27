-- DunnFlow schema
-- Three core tables: payments (failed events), retry_attempts (recovery actions),
-- audit_log (every decision made, including guardrail-blocked ones)

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS payments (
    payment_id      TEXT PRIMARY KEY,       -- e.g. "pay_xxx" (simulated or real test-mode id)
    customer_id     TEXT NOT NULL,
    customer_name   TEXT,
    customer_email  TEXT,
    amount          INTEGER NOT NULL,       -- in paise (Razorpay convention)
    currency        TEXT NOT NULL DEFAULT 'INR',
    raw_error_code  TEXT,                   -- e.g. "BAD_REQUEST_ERROR" / gateway decline code
    failure_reason  TEXT,                   -- human-readable reason from gateway
    failure_category TEXT,                  -- set by diagnosis module: insufficient_funds | card_expired | bank_timeout | other
    status          TEXT NOT NULL DEFAULT 'failed',  -- failed | recovered | exhausted | pending_retry
    retry_count     INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,                   -- ISO timestamp of last retry/action
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS retry_attempts (
    attempt_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id      TEXT NOT NULL REFERENCES payments(payment_id),
    attempt_number  INTEGER NOT NULL,
    action_type     TEXT NOT NULL,          -- retry_payment | send_update_card_message | auto_retry_same_card
    scheduled_for   TEXT,                   -- ISO timestamp when this action is/was due
    executed_at     TEXT,                   -- ISO timestamp when actually executed
    result          TEXT,                   -- success | failed | blocked | pending
    result_detail   TEXT,                   -- raw response / reason
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id      TEXT NOT NULL REFERENCES payments(payment_id),
    customer_id     TEXT NOT NULL,
    stage           TEXT NOT NULL,          -- detect | diagnose | decide | execute | outcome | guardrail_block
    failure_category TEXT,
    action_taken    TEXT,                   -- what was decided/executed (or "none" if blocked)
    guardrail_hit   TEXT,                   -- name of guardrail that blocked action, if any (else NULL)
    result          TEXT,                   -- success | failed | blocked | n/a
    detail          TEXT,                   -- free-text explanation, human-readable
    timestamp       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
CREATE INDEX IF NOT EXISTS idx_retry_payment_id ON retry_attempts(payment_id);
CREATE INDEX IF NOT EXISTS idx_audit_payment_id ON audit_log(payment_id);