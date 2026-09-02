-- DunnFlow
-- Razorpay-aligned subscription revenue recovery schema

PRAGMA foreign_keys = ON;

-- ============================================================
-- 1. BATCH RUNS
-- One row = one complete benchmark/demo execution.
-- ============================================================

CREATE TABLE IF NOT EXISTS batch_runs (
    batch_id            TEXT PRIMARY KEY,
    started_at          TEXT NOT NULL,
    completed_at        TEXT,

    status              TEXT NOT NULL DEFAULT 'running',
    -- running | completed | failed

    total_subscriptions INTEGER NOT NULL DEFAULT 0,
    total_invoices      INTEGER NOT NULL DEFAULT 0,

    amount_at_risk      INTEGER NOT NULL DEFAULT 0,
    amount_recovered    INTEGER NOT NULL DEFAULT 0,

    recovered_count     INTEGER NOT NULL DEFAULT 0,
    exhausted_count     INTEGER NOT NULL DEFAULT 0,
    in_progress_count   INTEGER NOT NULL DEFAULT 0,
    manual_review_count INTEGER NOT NULL DEFAULT 0
);

-- ============================================================
-- 2. SUBSCRIPTIONS
-- Mirrors the important Razorpay subscription lifecycle.
-- ============================================================

CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id            TEXT PRIMARY KEY,
    batch_id                   TEXT NOT NULL
        REFERENCES batch_runs(batch_id),

    razorpay_subscription_id   TEXT UNIQUE,

    customer_id                TEXT NOT NULL,
    customer_name              TEXT,
    customer_email             TEXT,

    plan_id                    TEXT,
    plan_name                  TEXT,

    amount                     INTEGER NOT NULL,
    currency                   TEXT NOT NULL DEFAULT 'INR',

    status                     TEXT NOT NULL DEFAULT 'active',
    -- authenticated | active | pending | halted |
    -- cancelled | completed | paused | expired

    current_cycle              INTEGER DEFAULT 1,
    total_cycles               INTEGER,

    retry_count                INTEGER NOT NULL DEFAULT 0,

    last_failure_category      TEXT,

    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL
);

-- ============================================================
-- 3. INVOICES
-- The actual revenue obligation that may be at risk.
-- ============================================================

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id                 TEXT PRIMARY KEY,
    batch_id                   TEXT NOT NULL
        REFERENCES batch_runs(batch_id),

    subscription_id            TEXT NOT NULL
        REFERENCES subscriptions(subscription_id),

    razorpay_invoice_id        TEXT UNIQUE,

    amount                     INTEGER NOT NULL,
    currency                   TEXT NOT NULL DEFAULT 'INR',

    status                     TEXT NOT NULL DEFAULT 'issued',
    -- issued | paid | cancelled | expired

    issued_at                  TEXT NOT NULL,
    paid_at                    TEXT,

    due_at                     TEXT,

    failure_category           TEXT,

    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL
);

-- ============================================================
-- 4. PAYMENT ATTEMPTS
-- Every payment attempt against an invoice.
-- ============================================================

CREATE TABLE IF NOT EXISTS payment_attempts (
    attempt_id                 INTEGER PRIMARY KEY AUTOINCREMENT,

    batch_id                   TEXT NOT NULL
        REFERENCES batch_runs(batch_id),

    invoice_id                 TEXT NOT NULL
        REFERENCES invoices(invoice_id),

    subscription_id            TEXT NOT NULL
        REFERENCES subscriptions(subscription_id),

    razorpay_payment_id        TEXT,

    attempt_number             INTEGER NOT NULL,

    attempt_type               TEXT NOT NULL,
    -- initial_charge | auto_retry | manual_retry |
    -- recovery_payment | customer_payment

    action_type                TEXT,
    -- retry_payment |
    -- payment_method_update |
    -- customer_action |
    -- manual_review

    scheduled_for              TEXT,
    executed_at                TEXT,

    result                     TEXT,
    -- success | failed | pending | blocked

    raw_error_code             TEXT,
    failure_reason             TEXT,

    gateway_status             TEXT,

    result_detail              TEXT,

    created_at                 TEXT NOT NULL
);

-- ============================================================
-- 5. RECOVERY ACTIONS
-- What DunnFlow decided to do.
-- Separate from actual payment attempts.
-- ============================================================

CREATE TABLE IF NOT EXISTS recovery_actions (
    action_id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    batch_id                   TEXT NOT NULL
        REFERENCES batch_runs(batch_id),

    subscription_id            TEXT NOT NULL
        REFERENCES subscriptions(subscription_id),

    invoice_id                 TEXT
        REFERENCES invoices(invoice_id),

    action_type                TEXT NOT NULL,
    -- retry_payment |
    -- payment_method_update |
    -- customer_action |
    -- manual_review |
    -- no_action

    reason                     TEXT NOT NULL,

    priority                   TEXT NOT NULL DEFAULT 'normal',
    -- low | normal | high | critical

    scheduled_for              TEXT,

    executed_at                TEXT,

    status                     TEXT NOT NULL DEFAULT 'planned',
    -- planned | executed | blocked | cancelled | awaiting_customer

    guardrail_hit              TEXT,

    created_at                 TEXT NOT NULL
);

-- ============================================================
-- 6. REVENUE EVENTS
-- Financial truth used for recovery measurement.
-- ============================================================

CREATE TABLE IF NOT EXISTS revenue_events (
    event_id                   INTEGER PRIMARY KEY AUTOINCREMENT,

    batch_id                   TEXT NOT NULL
        REFERENCES batch_runs(batch_id),

    subscription_id            TEXT NOT NULL
        REFERENCES subscriptions(subscription_id),

    invoice_id                 TEXT
        REFERENCES invoices(invoice_id),

    payment_attempt_id         INTEGER
        REFERENCES payment_attempts(attempt_id),

    event_type                 TEXT NOT NULL,
    -- revenue_at_risk |
    -- payment_failed |
    -- payment_captured |
    -- invoice_paid |
    -- recovery_confirmed

    amount                     INTEGER NOT NULL DEFAULT 0,

    razorpay_event_id          TEXT,

    event_timestamp            TEXT NOT NULL,

    detail                     TEXT
);

-- ============================================================
-- 7. AUDIT LOG
-- Complete explainability trail.
-- ============================================================

CREATE TABLE IF NOT EXISTS audit_log (
    log_id                     INTEGER PRIMARY KEY AUTOINCREMENT,

    batch_id                   TEXT NOT NULL
        REFERENCES batch_runs(batch_id),

    subscription_id            TEXT
        REFERENCES subscriptions(subscription_id),

    invoice_id                 TEXT
        REFERENCES invoices(invoice_id),

    payment_attempt_id         INTEGER
        REFERENCES payment_attempts(attempt_id),

    stage                      TEXT NOT NULL,
    -- detect | diagnose | decide | execute |
    -- webhook | outcome | guardrail_block

    failure_category           TEXT,

    action_taken               TEXT,

    guardrail_hit              TEXT,

    result                     TEXT,

    detail                     TEXT NOT NULL,

    timestamp                  TEXT NOT NULL
);

-- ============================================================
-- ============================================================
-- RAZORPAY WEBHOOK EVENTS
-- One row = one unique Razorpay webhook delivery event.
-- Used for webhook-level idempotency.
-- ============================================================

CREATE TABLE IF NOT EXISTS razorpay_webhook_events (
    event_id       TEXT PRIMARY KEY,
    event_type     TEXT NOT NULL,
    received_at    TEXT NOT NULL
);

-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_batch_runs_status
    ON batch_runs(status);

CREATE INDEX IF NOT EXISTS idx_subscriptions_batch
    ON subscriptions(batch_id);

CREATE INDEX IF NOT EXISTS idx_subscriptions_status
    ON subscriptions(status);

CREATE INDEX IF NOT EXISTS idx_invoices_batch
    ON invoices(batch_id);

CREATE INDEX IF NOT EXISTS idx_invoices_subscription
    ON invoices(subscription_id);

CREATE INDEX IF NOT EXISTS idx_payment_attempts_invoice
    ON payment_attempts(invoice_id);

CREATE INDEX IF NOT EXISTS idx_payment_attempts_batch
    ON payment_attempts(batch_id);

CREATE INDEX IF NOT EXISTS idx_recovery_actions_batch
    ON recovery_actions(batch_id);

CREATE INDEX IF NOT EXISTS idx_recovery_actions_status
    ON recovery_actions(status);

CREATE INDEX IF NOT EXISTS idx_revenue_events_batch
    ON revenue_events(batch_id);

CREATE INDEX IF NOT EXISTS idx_revenue_events_invoice
    ON revenue_events(invoice_id);

CREATE INDEX IF NOT EXISTS idx_audit_batch
    ON audit_log(batch_id);

CREATE INDEX IF NOT EXISTS idx_audit_subscription
    ON audit_log(subscription_id);
