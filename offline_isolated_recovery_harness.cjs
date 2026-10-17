'use strict';

// Offline-only DunnFlow regression tests.
// No backend, network, Razorpay checkout, or payment calls.

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const ROOT = process.cwd();
const JS_DIR = path.join(ROOT, 'static', 'js');

for (const file of ['state.js', 'api.js', 'metrics.js']) {
    if (!fs.existsSync(path.join(JS_DIR, file))) {
        throw new Error(`Required file not found: ${path.join(JS_DIR, file)}`);
    }
}

const SESSION = {
    session_id: 'sess_offline_001',
    invoice_id: 'inv_offline_001',
    batch_id: 'razorpay_isolated_test_offline',
    razorpay_order_id: 'order_offline_001',
    amount: 29900,
    currency: 'INR',
    invoice_status: 'issued',
    session_status: 'order_created',
    mode: 'razorpay_test_mode'
};

function makeElement(id) {
    const classes = new Set();
    const children = new Map();

    return {
        id,
        tagName: id === 'casesTable' ? 'TBODY' : 'DIV',
        textContent: '',
        innerHTML: '',
        hidden: false,
        disabled: false,
        dataset: {},
        style: {},
        value: '',
        href: '',
        classList: {
            add: (...names) => names.forEach(n => classes.add(n)),
            remove: (...names) => names.forEach(n => classes.delete(n)),
            contains: n => classes.has(n)
        },
        addEventListener() {},
        removeEventListener() {},
        setAttribute() {},
        getAttribute() { return null; },
        appendChild() {},
        querySelector(selector) {
            if (!children.has(selector)) {
                children.set(selector, makeElement(`${id}:${selector}`));
            }
            return children.get(selector);
        },
        querySelectorAll() { return []; },
        closest() { return null; },
        click() {}
    };
}

function makeResponse(session) {
    return {
        session_id: session.session_id,
        invoice_id: session.invoice_id,
        batch_id: session.batch_id,
        razorpay_order_id: session.razorpay_order_id,
        awaiting_payment: true,
        financial_execution_performed: false,
        detection: { status: 'detected' },
        diagnosis: { reason: 'offline test' },
        decision: { action: 'retry_payment' }
    };
}

function createEnvironment() {
    const elements = new Map();
    const listeners = new Map();

    const document = {
        readyState: 'loading',
        addEventListener(type, callback) {
            if (!listeners.has(type)) listeners.set(type, []);
            listeners.get(type).push(callback);
        },
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, makeElement(id));
            return elements.get(id);
        },
        querySelector() { return null; },
        querySelectorAll() { return []; },
        createElement(tag) { return makeElement(tag); },
        body: makeElement('body')
    };

    const calls = {
        recoverySessionIds: [],
        metricsBatchIds: [],
        createSessionCalls: 0,
        createOrderCalls: 0
    };

    let response = makeResponse(SESSION);

    const sandbox = {
        console: { log() {}, info() {}, warn() {}, error() {}, debug() {} },
        document,
        URL,
        URLSearchParams,
        setTimeout,
        clearTimeout,
        AbortController,
        structuredClone,
        fetch: async () => {
            throw new Error('Safety stop: unexpected network request');
        }
    };

    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    sandbox.crypto = { randomUUID: () => 'offline-uuid' };

    const context = vm.createContext(sandbox);

    for (const file of ['state.js', 'api.js']) {
        vm.runInContext(
            fs.readFileSync(path.join(JS_DIR, file), 'utf8'),
            context,
            { filename: file }
        );
    }

    sandbox.DunnFlowAPI = sandbox.DunnFlowAPI || {};
    sandbox.window.DunnFlowAPI.runIsolatedRazorpayRecovery =
        async sessionId => {
            calls.recoverySessionIds.push(sessionId);
            return structuredClone(response);
        };

    sandbox.window.DunnFlowAPI.createRazorpayDemoSession = async () => {
        calls.createSessionCalls++;
        return {
            session_id: 'unexpected-session',
            razorpay_order_id: 'unexpected-order'
        };
    };

    sandbox.window.DunnFlowAPI.getRazorpayCheckout = async () => {
        calls.createOrderCalls++;
        return { razorpay_order_id: 'unexpected-order' };
    };

    // Mock the global used by metrics.js. This also records the batch ID.
    let metricsFailure = false;

    sandbox.getMetrics = async batchId => {
        calls.metricsBatchIds.push(batchId);

        if (metricsFailure) {
            throw new Error('Intentional offline metrics failure');
        }

        return {
            exists: true,
            batch_id: batchId,
            amount_at_risk: SESSION.amount,
            historical_amount_at_risk: SESSION.amount,
            historical_invoices_at_risk: 1,
            recovered_count: 0,
            amount_recovered: 0,
            recovery_rate_pct: 0,
            in_progress_count: 1,
            blocked_count: 0,
            manual_review_count: 0
        };
    };

    vm.runInContext(
        fs.readFileSync(path.join(JS_DIR, 'metrics.js'), 'utf8'),
        context,
        { filename: 'metrics.js' }
    );

    const state = sandbox.DunnFlowState;
    state.mode = 'demo';
    state.batchId = SESSION.batch_id;
    state.invoiceId = SESSION.invoice_id;
    state.scenario = 'razorpayVideoDemo';
    state.razorpaySession = { ...SESSION };
    state.running = false;

    return {
        sandbox,
        calls,
        elements,
        setResponse(value) { response = value; },
        setMetricsFailure(value) { metricsFailure = value; }
    };
}

const tests = [];

function test(name, fn) {
    tests.push({ name, fn });
}

test('Recovery calls API with selected session ID', async () => {
    const env = createEnvironment();
    const result = await env.sandbox.DunnFlowMetrics.runRecovery();

    assert.deepEqual(env.calls.recoverySessionIds, [SESSION.session_id]);
    assert.equal(result.session_id, SESSION.session_id);
});

test('Valid recovery response leaves payment awaiting', async () => {
    const env = createEnvironment();
    const result = await env.sandbox.DunnFlowMetrics.runRecovery();

    assert.equal(result.awaitingCheckout, true);
    assert.equal(
        env.elements.get('outcomeResult').textContent,
        'AWAITING PAYMENT'
    );
    assert.equal(
        env.sandbox.DunnFlowState.lastExecution.result,
        'awaiting_payment'
    );
    assert.equal(
        env.sandbox.DunnFlowState.lastExecution.financial_execution_performed,
        false
    );
});

test('No duplicate session or order is created', async () => {
    const env = createEnvironment();
    await env.sandbox.DunnFlowMetrics.runRecovery();

    assert.equal(env.calls.createSessionCalls, 0);
    assert.equal(env.calls.createOrderCalls, 0);
    assert.equal(env.calls.recoverySessionIds.length, 1);
});

test('Metrics use the isolated session batch ID', async () => {
    const env = createEnvironment();
    await env.sandbox.DunnFlowMetrics.runRecovery();

    assert.deepEqual(env.calls.metricsBatchIds, [SESSION.batch_id]);
    assert.equal(
        env.sandbox.DunnFlowState.lastMetrics.batch_id,
        SESSION.batch_id
    );
});

test('Metrics failure does not overwrite awaiting-payment recovery', async () => {
    const env = createEnvironment();
    env.setMetricsFailure(true);

    const result = await env.sandbox.DunnFlowMetrics.runRecovery();

    assert.equal(result.awaitingCheckout, true);
    assert.equal(
        env.elements.get('outcomeResult').textContent,
        'AWAITING PAYMENT'
    );
    assert.equal(
        env.sandbox.DunnFlowState.lastExecution.result,
        'awaiting_payment'
    );
    assert.equal(
        env.sandbox.DunnFlowState.lastExecution.financial_execution_performed,
        false
    );
    assert.equal(env.calls.createSessionCalls, 0);
    assert.equal(env.calls.createOrderCalls, 0);
    assert.equal(env.calls.recoverySessionIds.length, 1);
});

test('Mismatched order response is rejected', async () => {
    const env = createEnvironment();

    env.setResponse({
        ...makeResponse(SESSION),
        razorpay_order_id: 'order_wrong'
    });

    await assert.rejects(
        env.sandbox.DunnFlowMetrics.runRecovery(),
        /did not match the prepared session\/order/
    );

    assert.equal(env.elements.get('outcomeResult').textContent, 'ERROR');
});

test('Missing awaiting-payment confirmation is rejected', async () => {
    const env = createEnvironment();

    env.setResponse({
        ...makeResponse(SESSION),
        awaiting_payment: false
    });

    await assert.rejects(
        env.sandbox.DunnFlowMetrics.runRecovery(),
        /did not match the prepared session\/order/
    );

    assert.equal(env.elements.get('outcomeResult').textContent, 'ERROR');
});

(async () => {
    let failures = 0;

    for (const item of tests) {
        try {
            await item.fn();
            process.stdout.write(`PASS: ${item.name}\n`);
        } catch (error) {
            failures++;
            process.stdout.write(`FAIL: ${item.name}\n`);
            process.stdout.write(
                `  ${error && error.stack ? error.stack : error}\n`
            );
        }
    }

    process.stdout.write(
        `\n${tests.length - failures}/${tests.length} checks passed.\n`
    );

    process.exitCode = failures === 0 ? 0 : 1;
})();

