/*
 * DunnFlow \u2014 Metrics & Recovery Orchestration
 *
 * Responsibilities:
 * - Render dashboard metrics.
 * - Render recovery pipeline state.
 * - Run Control Center batch recovery.
 * - Run Demo Lab invoice recovery.
 * - Keep Demo and Control execution paths completely separate.
 *
 * IMPORTANT:
 * - Execution mode comes ONLY from DunnFlowState.
 * - Navigation/scroll position never determines execution mode.
 * - Metrics refresh NEVER executes recovery.
 * - AI recommendations are displayed separately from deterministic policy.
 */

(function () {
    "use strict";


    const DEFAULT_BATCH =
        "benchmark_60_subscription_failures";


    /*
     * ------------------------------------------------------------------
     * DOM helpers
     * ------------------------------------------------------------------
     */

    function byId(id) {
        return document.getElementById(id);
    }


    function setText(id, value) {
        const element = byId(id);

        if (!element) {
            return;
        }

        element.textContent =
            value === null ||
            value === undefined
                ? "\u2014"
                : String(value);
    }


    function setHtml(id, html) {
        const element = byId(id);

        if (!element) {
            return;
        }

        element.innerHTML = html;
    }


    function showElement(id, visible) {
        const element = byId(id);

        if (!element) {
            return;
        }

        element.hidden = !visible;
    }


    /*
     * ------------------------------------------------------------------
     * Formatting
     * ------------------------------------------------------------------
     */

    function formatRupeesFromPaise(
        paise
    ) {
        const value =
            Number(paise);

        if (
            !Number.isFinite(value)
        ) {
            return "\u20B90.00";
        }

        return (
            "\u20B9" +
            (
                value / 100
            ).toLocaleString(
                "en-IN",
                {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                }
            )
        );
    }


    function formatPercent(
        value
    ) {
        const number =
            Number(value);

        if (
            !Number.isFinite(number)
        ) {
            return "0.0%";
        }

        return (
            number.toFixed(1) +
            "%"
        );
    }


    /*
     * Report dashboard formatting helpers.
     *
     * Report metrics use the same backend monetary unit
     * as the main dashboard: paise.
     */
    function formatReportCurrency(
        paise
    ) {
        return formatRupeesFromPaise(
            paise
        );
    }


    function formatReportPercent(
        value
    ) {
        return formatPercent(
            value
        );
    }


    function normalizePercentage(
        value
    ) {
        const number =
            Number(value);

        if (
            !Number.isFinite(number)
        ) {
            return 0;
        }

        /*
         * Backend metrics may expose recovery_rate_pct
         * directly as 49.5, while some payloads may expose
         * recovery_rate as 0.495.
         */
        if (
            number > 0 &&
            number <= 1
        ) {
            return number * 100;
        }

        return number;
    }


    /*
     * ------------------------------------------------------------------
     * Dashboard rendering
     * ------------------------------------------------------------------
     */

    function renderMetrics(
        metrics
    ) {
        if (!metrics) {
            return;
        }

        const risk =
            metrics.historical_amount_at_risk ??
            metrics.amount_at_risk ??
            metrics.revenue_at_risk ??
            0;

        const recovered =
            metrics.amount_recovered ??
            metrics.recovered_amount ??
            0;

        const rate =
            metrics.recovery_rate_pct ??
            metrics.recovery_rate ??
            0;

        const inProgress =
            metrics.in_progress_count ??
            metrics.in_progress ??
            0;

        const blocked =
            metrics.blocked_count ??
            metrics.guardrail_blocks ??
            0;

        const manualReview =
            metrics.manual_review_count ??
            0;

        setText(
            "riskAmount",
            formatRupeesFromPaise(risk)
        );

        setText(
            "recoveredAmount",
            formatRupeesFromPaise(recovered)
        );

        setText(
            "recoveryRate",
            formatPercent(
                normalizePercentage(rate)
            )
        );

        setText(
            "inProgress",
            inProgress
        );


        /*
         * Optional supporting dashboard fields.
         * These are harmless if the current template
         * does not contain them.
         */

        setText(
            "blockedCases",
            blocked
        );

        setText(
            "manualReviewCases",
            manualReview
        );


        DunnFlowState.lastMetrics =
            metrics;
    }


    /*
     * ------------------------------------------------------------------
     * Batch metrics loading
     * ------------------------------------------------------------------
     */

    async function refreshMetrics(
        batchId = null
    ) {
        const targetBatch =
            batchId ||
            getSelectedBatchId() ||
            DEFAULT_BATCH;

        try {
            const metrics =
                await getMetrics(
                    targetBatch
                );

            if (!metrics) {
                return null;
            }

            /*
             * Prevent a stale request from overwriting
             * metrics after the user changes the selected batch.
             */
            if (
                getSelectedBatchId() !==
                targetBatch
            ) {
                return null;
            }

            renderMetrics(
                metrics
            );

            DunnFlowState.lastMetrics =
                metrics;

            return metrics;

        } catch (error) {
            console.error(
                "DunnFlow metrics refresh failed:",
                error
            );

            throw error;
        }
    }


    /*
     * ------------------------------------------------------------------
     * Batch state initialization
     * ------------------------------------------------------------------
     */

    function initializeBatchState() {
        const batchSelect =
            byId("batchSelect");

        const batchId =
            batchSelect &&
            batchSelect.value
                ? batchSelect.value
                : DEFAULT_BATCH;

        /*
         * Batch selection is the reporting context.
         * Scenario cards must not replace this value.
         */
        if (batchSelect) {
            batchSelect.value =
                batchId;
        }

        enterControlMode(
            batchId
        );
    }


    /*
     * ------------------------------------------------------------------
     * Initial dashboard metrics
     * ------------------------------------------------------------------
     */

    function initializeMetrics() {
        const batchId =
            getSelectedBatchId() ||
            DEFAULT_BATCH;

        refreshMetrics(
            batchId
        ).catch(
            function (error) {
                console.error(
                    "DunnFlow initial metrics load failed:",
                    error
                );
            }
        );
    }



    /*
     * ------------------------------------------------------------------
     * Recovery pipeline UI
     * ------------------------------------------------------------------
     */

    function setPipelineStep(
        id,
        status
    ) {
        const element =
            byId(id);

        if (!element) {
            return;
        }

        element.classList.remove(
            "pending",
            "active",
            "complete",
            "success",
            "blocked",
            "error",
            "awaiting"
        );

        if (status) {
            element.classList.add(
                status
            );
        }

        const statusText =
            element.querySelector(
                ".step-status"
            );

        if (!statusText) {
            return;
        }

        const descriptions = {
            detect: "Identify revenue at risk",
            decide: "Choose safest recovery action",
            execute: "Execute within guardrails",
            outcome: "Track recovery result"
        };

        const labels = {
            pending: "PENDING",
            active: "RUNNING",
            complete: "COMPLETE",
            success: "VERIFIED",
            blocked: "BLOCKED",
            error: "ERROR",
            awaiting: "AWAITING PAYMENT"
        };

        const stageById = {
            detectStep: "detect",
            decideStep: "decide",
            executeStep: "execute",
            outcomeStep: "outcome"
        };

        const stage =
            stageById[id];

        statusText.textContent =
            labels[status] ||
            descriptions[stage] ||
            String(status).toUpperCase();
    }


    function resetPipeline() {
        [
            "detectStep",
            "decideStep",
            "executeStep",
            "outcomeStep"
        ].forEach(
            (id) =>
                setPipelineStep(
                    id,
                    "pending"
                )
        );
    }


    function updatePipeline(
        stage,
        status
    ) {
        const map = {
            detect:
                "detectStep",

            decide:
                "decideStep",

            execute:
                "executeStep",

            outcome:
                "outcomeStep"
        };

        const id =
            map[stage];

        if (id) {
            setPipelineStep(
                id,
                status
            );
        }

        const pipelineLabels = {
            pending: "PENDING",
            active: "RUNNING",
            complete: "COMPLETE",
            success: "VERIFIED",
            blocked: "BLOCKED",
            error: "ERROR"
        };

        let pipelineLabel =
            pipelineLabels[status] ||
            (status
                ? String(status).toUpperCase()
                : "READY");

        if (
            status === "pending" &&
            DunnFlowState.demoStage ===
                "scheduled" &&
            (
                stage === "execute" ||
                stage === "outcome"
            )
        ) {
            pipelineLabel = "SCHEDULED";
        }

        setText(
            "pipelineStatus",
            pipelineLabel
        );
    }


    /*
     * ------------------------------------------------------------------
     * Recovery Cases table
     * ------------------------------------------------------------------
     */

    function getCasesBody() {
        const table =
            byId("casesTable");

        if (!table) {
            return null;
        }

        if (
            table.tagName ===
            "TBODY"
        ) {
            return table;
        }

        return (
            table.querySelector("tbody") ||
            table
        );
    }


    function clearCases() {
        const body =
            getCasesBody();

        if (!body) {
            return;
        }

        body.innerHTML = "";
    }


    function createCell(
        text,
        className = ""
    ) {
        const cell =
            document.createElement("td");

        if (className) {
            cell.className =
                className;
        }

        cell.textContent =
            text === null ||
            text === undefined ||
            text === ""
                ? "\u2014"
                : String(text);

        return cell;
    }


    function renderCases(
        cases
    ) {
        const body =
            getCasesBody();

        if (!body) {
            return;
        }

        clearCases();

        if (
            !Array.isArray(cases) ||
            cases.length === 0
        ) {
            const row =
                document.createElement("tr");

            const cell =
                document.createElement("td");

            cell.colSpan = 8;

            cell.textContent =
                "No recovery cases found.";

            row.appendChild(cell);
            body.appendChild(row);

            return;
        }


        cases.forEach((decision) => {
            const row =
                document.createElement("tr");


            const failureCategory =
                decision.failure_category ||
                decision.category ||
                "unknown";


            const action =
                decision.action_type ||
                decision.decision ||
                decision.action ||
                "\u2014";


            const status =
                decision.status ||
                decision.result ||
                decision.outcome ||
                "\u2014";


            const priority =
                decision.priority ??
                "\u2014";


            const scheduledFor =
                decision.scheduled_for ||
                "\u2014";


            const guardrail =
                decision.guardrail_hit ||
                "\u2014";


            row.appendChild(
                createCell(
                    failureCategory
                )
            );

            row.appendChild(
                createCell(
                    action
                )
            );

            row.appendChild(
                createCell(
                    priority
                )
            );

            row.appendChild(
                createCell(
                    scheduledFor
                )
            );

            row.appendChild(
                createCell(
                    status
                )
            );

            row.appendChild(
                createCell(
                    guardrail
                )
            );


            body.appendChild(row);
        });
    }


    /*
     * ------------------------------------------------------------------
     * AI recommendation presentation
     * ------------------------------------------------------------------
     */

    function extractAIRecommendation(
        payload
    ) {
        if (!payload) {
            return null;
        }

        const reconciliation =
            payload.ai_reconciliation;

        /*
         * Backend Decision Intelligence response:
         *
         * ai_available
         * ai_action
         * deterministic_action
         * result
         * detail
         *
         * Normalize it into the presentation contract
         * expected by renderAIRecommendation().
         */
        if (reconciliation) {
            return {
                available:
                    reconciliation.ai_available === true,

                recommended_action:
                    reconciliation.ai_action ||
                    "?",

                agreement:
                    reconciliation.result ===
                    "agreement",

                reason:
                    reconciliation.detail ||
                    ""
            };
        }

        return (
            payload.ai_recommendation ||
            payload.ai ||
            payload.recommendation ||
            null
        );
    }


    function renderAIRecommendation(
        payload
    ) {
        const ai =
            extractAIRecommendation(
                payload
            );

        if (!ai) {
            return;
        }


        const available =
            ai.available !== false;


        const recommendation =
            ai.recommended_action ||
            ai.action ||
            ai.recommendation ||
            "\u2014";


        const confidence =
            ai.confidence;


        const agreement =
            ai.agreement;


        const reason =
            ai.reason ||
            ai.explanation ||
            "";


        /*
         * Prefer dedicated elements if they exist.
         * Fall back to the existing pipeline status.
         */

        setText(
            "aiRecommendation",
            available
                ? recommendation
                : "AI unavailable"
        );


        if (
            confidence !== undefined &&
            confidence !== null
        ) {
            setText(
                "aiConfidence",
                `${(
                    Number(confidence) * 100
                ).toFixed(0)}%`
            );
        }


        if (
            agreement !== undefined &&
            agreement !== null
        ) {
            setText(
                "aiAgreement",
                agreement
                    ? "AGREES"
                    : "ADVISORY DIFFERENCE"
            );
        }


        if (reason) {
            setText(
                "aiReason",
                reason
            );
        }
    }


    /*
     * ------------------------------------------------------------------
     * Deterministic decision presentation
     * ------------------------------------------------------------------
     */

    function renderDeterministicDecision(
        decision
    ) {
        if (!decision) {
            return;
        }

        const action =
            decision.action_type ||
            decision.decision ||
            decision.action ||
            "\u2014";


        setText(
            "deterministicDecision",
            action
        );


        if (
            decision.priority !==
            undefined
        ) {
            setText(
                "decisionPriority",
                decision.priority
            );
        }


        if (
            decision.guardrail_hit
        ) {
            setText(
                "decisionGuardrail",
                decision.guardrail_hit
            );
        }
    }


    /*
     * ------------------------------------------------------------------
     * Outcome presentation
     * ------------------------------------------------------------------
     */

    function renderExecutionOutcome(
        result
    ) {
        if (!result) {
            return;
        }

        const recovered =
            result.recovered === true;


        const status =
            result.status ||
            result.result ||
            "unknown";


        const amount =
            result.amount_recovered ??
            result.amountRecovered ??
            0;


        if (recovered) {
            setText(
                "outcomeResult",
                "RECOVERED"
            );

            if (
                Number(amount) > 0
            ) {
                setText(
                    "outcomeAmount",
                    formatRupeesFromPaise(
                        amount
                    )
                );
            }

            updatePipeline(
                "outcome",
                "success"
            );

            if (
                window.DunnFlowLiveFeed
            ) {
                window.DunnFlowLiveFeed
                    .recoveryVerified(
                        Number(amount)
                    );
            }

            return;
        }


        if (
            status === "blocked" ||
            result.guardrail_hit
        ) {
            setText(
                "outcomeResult",
                "BLOCKED"
            );

            updatePipeline(
                "outcome",
                "blocked"
            );

            if (
                window.DunnFlowLiveFeed
            ) {
                window.DunnFlowLiveFeed
                    .recoveryBlocked(
                        result.guardrail_hit ||
                        result.detail ||
                        "Deterministic guardrail"
                    );
            }

            return;
        }


        if (
            status === "cancelled" ||
            result.result ===
                "not_executed"
        ) {
            setText(
                "outcomeResult",
                "MANUAL REVIEW"
            );

            updatePipeline(
                "outcome",
                "blocked"
            );

            if (
                window.DunnFlowLiveFeed
            ) {
                window.DunnFlowLiveFeed
                    .manualReview(
                        result.detail ||
                        "Automatic execution was not performed."
                    );
            }

            return;
        }


        setText(
            "outcomeResult",
            status
                .toUpperCase()
        );
    }


    /*
     * ------------------------------------------------------------------
     * Non-executing Demo Lab case inspection
     * ------------------------------------------------------------------
     */

    async function inspectSelectedDemoCase(
        invoiceId
    ) {
        if (!invoiceId) {
            return;
        }

        try {
            /*
             * Decision Intelligence inspection is strictly read-only.
             *
             * Use the dedicated inspection endpoint only.
             * It evaluates diagnosis, deterministic policy, and AI
             * reconciliation without creating a recovery action,
             * executing payment recovery, or creating a Razorpay order.
             */
            const inspected =
                await inspectDemoCase(
                    invoiceId
                );

            const diagnosis =
                inspected &&
                inspected.diagnosis
                    ? inspected.diagnosis
                    : null;

            const deterministicDecision =
                inspected &&
                inspected.decision
                    ? inspected.decision
                    : null;

            DunnFlowState.lastDiagnosis =
                diagnosis;

            DunnFlowState.lastDecision =
                deterministicDecision;

            DunnFlowState.lastExecution =
                null;

            /*
             * Render the AI recommendation and deterministic
             * authorization independently.
             */
            renderAIRecommendation(
                inspected
            );

            renderDeterministicDecision(
                deterministicDecision
            );

            const category =
                diagnosis &&
                (
                    diagnosis.category ||
                    diagnosis.failure_category
                )
                    ? (
                        diagnosis.category ||
                        diagnosis.failure_category
                    )
                    : "unknown";

            setText(
                "failureDiagnosis",
                category
            );

            setText(
                "failureReason",
                diagnosis &&
                (
                    diagnosis.reason ||
                    diagnosis.failure_reason
                )
                    ? (
                        diagnosis.reason ||
                        diagnosis.failure_reason
                    )
                    : "No failure reason recorded."
            );

            renderDeterministicDecision(
                deterministicDecision
            );

            return inspected;

        } catch (error) {
            console.error(
                "DunnFlow AI inspection failed:",
                error
            );

            return null;
        }
    }


    /*
     * ------------------------------------------------------------------
     * Unified recovery entry point
     * ------------------------------------------------------------------
     */

    async function runRecovery() {
        if (
            DunnFlowState.running
        ) {
            return;
        }


        /*
         * IMPORTANT:
         *
         * Mode is determined ONLY by DunnFlowState.
         *
         * It does not matter which section is visible.
         * It does not matter which navigation link is active.
         * It does not matter where the page was scrolled.
         */
        const mode =
            DunnFlowState.mode;


        setRecoveryRunning(
            true
        );


        const runButton =
            byId("runBatchBtn");


        if (runButton) {
            runButton.disabled =
                true;

            runButton.dataset.originalText =
                runButton.textContent;

            runButton.textContent =
                "RUNNING...";
        }


        try {
            resetRecoveryResult();


            if (
                mode === "demo"
            ) {
                
                const selectedInvoiceId =
                    getSelectedDemoInvoiceId();

                console.info(
                    "DunnFlow: Demo recovery target",
                    {
                        mode:
                            DunnFlowState.mode,
                        scenario:
                            DunnFlowState.scenario,
                        invoiceId:
                            selectedInvoiceId,
                        demoStage:
                            DunnFlowState.demoStage,
                        running:
                            DunnFlowState.running
                    }
                );

                if (!selectedInvoiceId) {
                    throw new Error(
                        "No Demo Lab scenario is selected."
                    );
                }

                /*
                 * Razorpay Test Mode always executes against
                 * the dedicated Razorpay demo invoice.
                 */
                if (
                    DunnFlowState.scenario ===
                        "razorpayVideoDemo" &&
                    selectedInvoiceId !==
                        "inv_dunnflow_001"
                ) {
                    throw new Error(
                        "Razorpay Test Mode target mismatch: expected inv_dunnflow_001, got " +
                        selectedInvoiceId
                    );
                }

                return await runDemoRecovery(
                    selectedInvoiceId
                );

            }


            return await runControlRecovery(
                getSelectedBatchId()
            );

        } catch (error) {
            console.error(
                "DunnFlow recovery failed:",
                error
            );


            updatePipeline(
                "outcome",
                "error"
            );


            setText(
                "outcomeResult",
                "ERROR"
            );


            if (
                window.DunnFlowLiveFeed
            ) {
                window.DunnFlowLiveFeed
                    .error(
                        error.message ||
                        "Recovery failed."
                    );
            }


            throw error;

        } finally {
            setRecoveryRunning(
                false
            );


            if (runButton) {
                runButton.disabled =
                    false;

                if (
                    mode === "demo" &&
                    DunnFlowState.demoStage ===
                        "scheduled"
                ) {
                    runButton.textContent =
                        "EXECUTE SCHEDULED RECOVERY";
                } else {
                    runButton.textContent =
                        "RUN RECOVERY";
                }
            }
        }
    }


    /*
     * ------------------------------------------------------------------
     * Control Center recovery
     * ------------------------------------------------------------------
     */

    async function runControlRecovery(
        batchId
    ) {
        if (!batchId) {
            throw new Error(
                "No Control Center batch selected."
            );
        }


        if (
            window.DunnFlowLiveFeed
        ) {
            window.DunnFlowLiveFeed
                .recoveryStarted(
                    "Control Center batch recovery started."
                );
        }


        resetPipeline();

        updatePipeline(
            "detect",
            "active"
        );


        const detected =
            await detectBatch(
                batchId
            );


        updatePipeline(
            "detect",
            "complete"
        );


        if (
            window.DunnFlowLiveFeed
        ) {
            window.DunnFlowLiveFeed
                .pipeline(
                    "Detection",
                    "Revenue-at-risk cases identified."
                );
        }


        updatePipeline(
            "decide",
            "active"
        );


        const decided =
            await decideBatch(
                batchId
            );


        updatePipeline(
            "decide",
            "complete"
        );


        if (
            window.DunnFlowLiveFeed
        ) {
            window.DunnFlowLiveFeed
                .decisionCompleted(
                    "Deterministic recovery policy applied."
                );
        }


        updatePipeline(
            "execute",
            "active"
        );


        const executed =
            await executeBatch(
                batchId
            );


        updatePipeline(
            "execute",
            "complete"
        );


        updatePipeline(
            "outcome",
            "active"
        );


        const metrics =
            await refreshMetrics(
                batchId
            );


        renderExecutionOutcome(
            executed
        );


        updatePipeline(
            "outcome",
            executed &&
            executed.recovered
                ? "success"
                : "complete"
        );


        DunnFlowState.lastDiagnosis =
            detected;

        DunnFlowState.lastDecision =
            decided;

        DunnFlowState.lastExecution =
            executed;


        return {
            detected,
            decided,
            executed,
            metrics
        };
    }




    /*
     * ------------------------------------------------------------------
     * Demo Lab case-level metrics
     * ------------------------------------------------------------------
     *
     * Demo cards represent one invoice/case.
     *
     * Control Center metrics remain batch-level.
     * Demo metrics are derived only from the selected invoice
     * returned by GET /api/demo/cases/{invoiceId}.
     *
     * This function is read-only:
     * - no detection
     * - no decision
     * - no execution
     * - no payment
     */

    function renderDemoCaseMetrics(caseData) {
        if (!caseData || !caseData.invoice) {
            return;
        }

        const invoice =
            caseData.invoice;

        const decision =
            caseData.decision ||
            {};

        const amount =
            Number(invoice.amount || 0);

        const isPaid =
            invoice.status === "paid" ||
            Boolean(invoice.paid_at);

        const isBlocked =
            decision.decision === "blocked" ||
            Boolean(decision.guardrail_hit);

        const isManualReview =
            decision.decision === "manual_review" ||
            decision.action_type === "manual_review";

        /*
         * A paid invoice is no longer revenue at risk.
         * An unpaid invoice remains at risk.
         */
        const revenueAtRisk =
            isPaid
                ? 0
                : amount;

        const recoveredAmount =
            isPaid
                ? amount
                : 0;

        const recoveryRate =
            amount > 0
                ? (
                    recoveredAmount /
                    amount
                ) * 100
                : 0;

        /*
         * Only a genuinely active/scheduled recovery counts
         * as "in progress".
         *
         * Blocked and manual-review cases are terminal
         * decision outcomes, not active recovery.
         */
        const casesInProgress =
            !isPaid &&
            !isBlocked &&
            !isManualReview &&
            (
                decision.decision === "scheduled" ||
                decision.status === "scheduled"
            )
                ? 1
                : 0;

        const caseMetrics = {
            batch_id:
                invoice.batch_id,

            invoice_id:
                invoice.invoice_id,

            historical_invoices_at_risk:
                isPaid ? 0 : 1,

            historical_amount_at_risk:
                revenueAtRisk,

            recovered_count:
                isPaid ? 1 : 0,

            amount_recovered:
                recoveredAmount,

            recovery_rate_pct:
                recoveryRate,

            in_progress_count:
                casesInProgress,

            blocked_count:
                isBlocked ? 1 : 0,

            manual_review_count:
                isManualReview ? 1 : 0,

            demo_case:
                caseData.demo_case || null
        };

        renderMetrics(
            caseMetrics
        );

        return caseMetrics;
    }


    async function refreshSelectedDemoMetrics(
        invoiceId
    ) {
        if (!invoiceId) {
            return null;
        }

        try {
            const caseData =
                await getDemoCase(
                    invoiceId
                );

            /*
             * Ignore the response if the user switched
             * to another mode/case while the request was
             * in flight.
             */
            if (
                DunnFlowState.mode !== "demo" ||
                DunnFlowState.invoiceId !== invoiceId
            ) {
                return null;
            }

            const metrics =
                renderDemoCaseMetrics(
                    caseData
                );

            DunnFlowState.lastMetrics =
                metrics;

            return metrics;

        } catch (error) {
            console.error(
                "DunnFlow Demo case metrics refresh failed:",
                error
            );

            return null;
        }
    }


    /*
     * ------------------------------------------------------------------
     * Demo Lab recovery
     * ------------------------------------------------------------------
     */

    async function runDemoRecovery(
        invoiceId
    ) {
        if (!invoiceId) {
            throw new Error(
                "No Demo Lab invoice selected."
            );
        }


        /*
         * Demo recovery is intentionally two-stage:
         *
         *   idle       -> diagnose + decide + schedule
         *   scheduled -> execute the already-planned action
         *
         * This gives the judge a visible scheduled-recovery
         * checkpoint before financial execution occurs.
         */
        /*
         * A completed Demo Lab recovery is terminal until
         * the user selects another scenario.
         *
         * Never re-run diagnosis/decision/execution for the
         * same completed demo case.
         */
        if (
            DunnFlowState.demoStage ===
            "completed"
        ) {
            return {
                observed: null,
                diagnosis:
                    DunnFlowState.lastDiagnosis,
                decided:
                    DunnFlowState.lastDecision,
                executed:
                    DunnFlowState.lastExecution,
                finalAction:
                    DunnFlowState.lastExecution ||
                    DunnFlowState.lastDecision ||
                    null,
                metrics:
                    DunnFlowState.lastMetrics,
                completed: true,
                no_op: true
            };
        }


        if (
            DunnFlowState.demoStage ===
            "scheduled"
        ) {
            updatePipeline(
                "execute",
                "active"
            );

            const executedResponse =
                await executeDemoCase(
                    invoiceId
                );

            const executed =
                executedResponse &&
                executedResponse.execution
                    ? executedResponse.execution
                    : executedResponse;

            updatePipeline(
                "execute",
                "complete"
            );

            DunnFlowState.lastExecution =
                executed;

            renderExecutionOutcome(
                executed
            );

            const deterministicDecision =
                DunnFlowState.lastDecision ||
                {};

            const category =
                deterministicDecision.failure_category ||
                DunnFlowState.lastDiagnosis?.category ||
                DunnFlowState.lastDiagnosis?.failure_category ||
                "unknown";

            renderCases([
                {
                    ...deterministicDecision,

                    failure_category:
                        category,

                    status:
                        executed.status ||
                        executed.result ||
                        deterministicDecision.status ||
                        deterministicDecision.result ||
                        "?",

                    result:
                        executed.result ||
                        deterministicDecision.result ||
                        "?",

                    guardrail_hit:
                        executed.guardrail_hit ||
                        deterministicDecision.guardrail_hit ||
                        null,

                    scheduled_for:
                        executed.scheduled_for ||
                        deterministicDecision.scheduled_for ||
                        null
                }
            ]);

            const metrics =
                await refreshMetrics(
                    getSelectedBatchId()
                );

            DunnFlowState.lastMetrics =
                metrics;

            DunnFlowState.demoStage =
                "completed";

            updatePipeline(
                "outcome",
                executed &&
                executed.recovered
                    ? "success"
                    : executed &&
                      (
                          executed.status ===
                              "blocked" ||
                          executed.status ===
                              "cancelled" ||
                          executed.result ===
                              "not_executed"
                      )
                        ? "blocked"
                        : "complete"
            );

            return {
                observed: null,
                diagnosis:
                    DunnFlowState.lastDiagnosis,
                decided:
                    DunnFlowState.lastDecision,
                executed,
                finalAction:
                    executed.action ||
                    executed.recovery_action ||
                    executed,
                metrics
            };
        }


        if (
            window.DunnFlowLiveFeed
        ) {
            window.DunnFlowLiveFeed
                .recoveryStarted(
                    "Demo recovery started."
                );
        }


        resetPipeline();


        /*
         * --------------------------------------------------------------
         * OBSERVE / DIAGNOSE
         * --------------------------------------------------------------
         */

        updatePipeline(
            "detect",
            "active"
        );


        const observed =
            await getDemoCase(
                invoiceId
            );


        updatePipeline(
            "detect",
            "complete"
        );


        const diagnosis =
            observed.diagnosis ||
            observed;


        DunnFlowState.lastDiagnosis =
            diagnosis;


        const category =
            diagnosis.category ||
            diagnosis.failure_category ||
            "unknown";


        if (
            window.DunnFlowLiveFeed
        ) {
            window.DunnFlowLiveFeed
                .diagnosisCompleted(
                    category
                );
        }


        /*
         * --------------------------------------------------------------
         * DECIDE
         * --------------------------------------------------------------
         */

        updatePipeline(
            "decide",
            "active"
        );


        const decided =
            await decideDemoCase(
                invoiceId
            );


        updatePipeline(
            "decide",
            "complete"
        );


        const deterministicDecision =
            decided.decision ||
            decided;


        DunnFlowState.lastDecision =
            deterministicDecision;


        renderAIRecommendation(
            decided
        );


        renderDeterministicDecision(
            deterministicDecision
        );


        renderCases([
            {
                ...deterministicDecision,

                failure_category:
                    category
            }
        ]);


        if (
            window.DunnFlowLiveFeed
        ) {
            window.DunnFlowLiveFeed
                .decisionCompleted(
                    deterministicDecision.action_type ||
                    deterministicDecision.decision ||
                    "policy decision"
                );
        }


        /*
         * --------------------------------------------------------------
         * SCHEDULED RECOVERY CHECKPOINT
         * --------------------------------------------------------------
         *
         * The first Demo click stops here.
         * The deterministic decision and scheduled_for timestamp
         * remain visible. No financial execution occurs yet.
         */

        
        /*
         * --------------------------------------------------------------
         * GUARDED / BLOCKED CHECKPOINT
         * --------------------------------------------------------------
         *
         * If deterministic policy already blocked the recovery action,
         * there is intentionally no planned action to execute.
         * The demo therefore terminates safely as BLOCKED.
         */

        const decisionStatus =
            deterministicDecision.status ||
            deterministicDecision.result ||
            "";

        const decisionGuardrail =
            deterministicDecision.guardrail_hit ||
            null;

        const decisionIsBlocked =
            decisionStatus === "blocked" ||
            Boolean(decisionGuardrail);

        if (decisionIsBlocked) {

            DunnFlowState.lastExecution =
                null;

            updatePipeline(
                "execute",
                "complete"
            );

            setText(
                "outcomeResult",
                "BLOCKED"
            );

            updatePipeline(
                "outcome",
                "blocked"
            );

            renderCases([
                {
                    ...deterministicDecision,

                    failure_category:
                        category,

                    status:
                        decisionStatus ||
                        "blocked",

                    result:
                        deterministicDecision.result ||
                        "not_executed",

                    guardrail_hit:
                        decisionGuardrail,

                    scheduled_for:
                        null
                }
            ]);

            const blockedMetrics =
                await refreshMetrics(
                    getSelectedBatchId()
                );

            DunnFlowState.lastMetrics =
                blockedMetrics;

            DunnFlowState.demoStage =
                "completed";

            if (
                window.DunnFlowLiveFeed
            ) {
                window.DunnFlowLiveFeed
                    .recoveryStarted(
                        decisionGuardrail
                            ? `Recovery blocked safely by guardrail: ${decisionGuardrail}. No payment attempt was created.`
                            : "Recovery blocked safely by deterministic policy. No payment attempt was created."
                    );
            }

            return {
                observed,
                diagnosis,
                decided,
                scheduled: false,
                blocked: true,
                executed: null,
                finalAction:
                    deterministicDecision.action_type ||
                    deterministicDecision.decision ||
                    null,
                metrics:
                    blockedMetrics
            };
        }

if (DunnFlowState.scenario === "razorpayVideoDemo") {

            updatePipeline(
                "execute",
                "active"
            );

            const executedResponse =
                await executeDemoCase(
                    invoiceId
                );

            const executed =
                executedResponse &&
                executedResponse.execution
                    ? executedResponse.execution
                    : executedResponse;

            updatePipeline(
                "execute",
                "complete"
            );

            DunnFlowState.lastExecution =
                executed;

            const razorpayPending =
                executed &&
                (
                    executed.status === "pending" ||
                    executed.result === "pending" ||
                    Boolean(executed.razorpay_order_id)
                );

            renderCases([
                {
                    ...deterministicDecision,
                    failure_category: category,
                    status:
                        executed?.status ||
                        executed?.result ||
                        deterministicDecision.status ||
                        deterministicDecision.result ||
                        "?",
                    result:
                        executed?.result ||
                        deterministicDecision.result ||
                        "?",
                    guardrail_hit:
                        executed?.guardrail_hit ||
                        deterministicDecision.guardrail_hit ||
                        null,
                    scheduled_for:
                        executed?.scheduled_for ||
                        deterministicDecision.scheduled_for ||
                        null
                }
            ]);

            const razorpayMetrics =
                await refreshMetrics(
                    getSelectedBatchId()
                );

            DunnFlowState.lastMetrics =
                razorpayMetrics;

            if (razorpayPending) {
                DunnFlowState.demoStage =
                    "completed";

                setText(
                    "outcomeResult",
                    "AWAITING PAYMENT"
                );

                updatePipeline(
                    "outcome",
                    "awaiting"
                );

                if (window.DunnFlowLiveFeed) {
                    window.DunnFlowLiveFeed.add(
                        "Razorpay Test Mode order created. Awaiting customer payment.",
                        "info"
                    );
                }
            } else {
                DunnFlowState.demoStage =
                    "completed";

                renderExecutionOutcome(
                    executed
                );

                updatePipeline(
                    "outcome",
                    executed && executed.recovered
                        ? "success"
                        : executed &&
                          (
                              executed.status === "blocked" ||
                              executed.status === "cancelled" ||
                              executed.result === "not_executed"
                          )
                            ? "blocked"
                            : "complete"
                );
            }

            return {
                observed,
                diagnosis,
                decided,
                scheduled: false,
                executed,
                awaiting_payment: razorpayPending,
                finalAction:
                    executed?.action ||
                    executed?.recovery_action ||
                    deterministicDecision.action_type ||
                    deterministicDecision.decision ||
                    executed,
                metrics: razorpayMetrics
            };
        }


        DunnFlowState.demoStage =
            "scheduled";

        updatePipeline(
            "execute",
            "pending"
        );

        updatePipeline(
            "outcome",
            "pending"
        );

        setText(
            "outcomeResult",
            "SCHEDULED"
        );

        if (
            window.DunnFlowLiveFeed
        ) {
            window.DunnFlowLiveFeed
                .recoveryStarted(
                    "Recovery scheduled. Execution is waiting for the next step."
                );
        }

        return {
            observed,
            diagnosis,
            decided,
            scheduled: true,
            executed: null,
            finalAction:
                deterministicDecision.action_type ||
                deterministicDecision.decision ||
                null,
            metrics:
                DunnFlowState.lastMetrics
        };

    }




    /*
     * Initialize Demo Lab inspection during normal page setup.
     *
     * This is deliberately outside runRecovery().
     * Selecting a Demo Lab case must inspect it without
     * executing a financial recovery action.
     */
    initializeDemoInspection();


    /*
     * ------------------------------------------------------------------
     * Demo Lab selection inspection
     * ------------------------------------------------------------------
     */

    function initializeDemoInspection() {
    DunnFlowState.demoStage = null;
    DunnFlowState.lastDiagnosis = null;
    DunnFlowState.lastDecision = null;
    DunnFlowState.lastExecution = null;
    DunnFlowState.lastMetrics = null;

    /*
     * Scenario selection is intentionally passive.
     * Selecting a scenario card changes only the recovery
     * target. It does NOT change dashboard batch metrics.
     *
     * Read-only AI/policy inspection is triggered explicitly
     * by the INSPECT AI DECISION button.
     */
    return;
}

function setReportInspector(title, type, body) {
    setText("reportInspectorTitle", title);
    setText("reportInspectorType", type || "READ-ONLY");

    const target = document.getElementById("reportInspectorBody");

    if (target) {
        target.innerHTML = body;
    }
}

function inspectReportMetric(kind, item, row) {
    clearReportSelection();

    if (row) {
        row.classList.add("is-selected");
    }

    if (kind === "category") {
        const total = Number(item.total || 0);
        const recovered = Number(item.recovered || 0);
        const rate = total > 0 ? (recovered / total) * 100 : 0;

        setReportInspector(
            reportCategoryLabel(item.failure_category),
            "FAILURE CATEGORY - READ-ONLY",
            '<div class="report-inspector-stat"><span>Total cases</span><strong>' + total + '</strong></div>' +
            '<div class="report-inspector-stat"><span>Recovered</span><strong>' + recovered + '</strong></div>' +
            '<div class="report-inspector-stat"><span>Recovery rate</span><strong>' + formatReportPercent(rate) + '</strong></div>' +
            '<p class="report-inspector-note">Diagnosis is evaluated from the recorded payment failure. This report view does not execute or authorize recovery.</p>'
        );

        return;
    }

    const actions = Number(item.actions || 0);
    const executed = Number(item.executed || 0);
    const blocked = Number(item.blocked || 0);

    setReportInspector(
        reportActionLabel(item.action_type),
        "RECOVERY STRATEGY - READ-ONLY",
        '<div class="report-inspector-stat"><span>Actions</span><strong>' + actions + '</strong></div>' +
        '<div class="report-inspector-stat"><span>Executed</span><strong>' + executed + '</strong></div>' +
        '<div class="report-inspector-stat"><span>Blocked</span><strong>' + blocked + '</strong></div>' +
        '<p class="report-inspector-note">Deterministic policy remains the final authority. Report inspection is read-only and cannot trigger recovery.</p>'
    );
}

function bindReportBreakdownInteractions() {
    document.querySelectorAll(
        "#reportCategoryBreakdown .report-breakdown-row, #reportActionBreakdown .report-breakdown-row"
    ).forEach(function (row) {
        if (row.dataset.reportBound === "true") {
            return;
        }

        row.addEventListener("click", function () {
            const kind = row.dataset.reportKind;
            const raw = row.dataset.reportItem;

            if (!kind || !raw) {
                return;
            }

            try {
                inspectReportMetric(kind, JSON.parse(raw), row);
            } catch (error) {
                console.error("DunnFlow report inspection failed:", error);
            }
        });

        row.dataset.reportBound = "true";
    });
}

function renderReportRows(
    containerId,
    rows,
    emptyMessage,
    rowRenderer
) {
    const container =
        document.getElementById(
            containerId
        );

    if (!container) {
        return;
    }

    if (
        !Array.isArray(rows) ||
        rows.length === 0
    ) {
        container.innerHTML =
            '<div class="report-empty-state">' +
            emptyMessage +
            '</div>';

        return;
    }

    container.innerHTML =
        rows
            .map(rowRenderer)
            .join("");
}


function renderReportDashboard(metrics) {
        if (!metrics || metrics.exists === false) {
            return;
        }

        setText(
            "reportRevenueAtRisk",
            formatReportCurrency(
                metrics.historical_amount_at_risk
            )
        );

        setText(
            "reportRecoveredAmount",
            formatReportCurrency(
                metrics.amount_recovered
            )
        );

        setText(
            "reportRecoveryRate",
            formatReportPercent(
                metrics.recovery_rate_pct
            )
        );

        setText(
            "reportRecoveredCases",
            `${Number(metrics.recovered_count || 0)} / ${Number(metrics.historical_invoices_at_risk || 0)}`
        );


        renderReportRows(
            "reportCategoryBreakdown",
            metrics.failure_categories,
            "No failure-category metrics available.",
            function (item) {
                const total =
                    Number(item.total || 0);

                const recovered =
                    Number(item.recovered || 0);

                const rate =
                    total > 0
                        ? (recovered / total) * 100
                        : 0;

                return `
                    <div class="report-breakdown-row" data-report-kind="category" data-report-item='${JSON.stringify(item)}'>
                        <div class="report-breakdown-main">
                            <strong>
                                ${reportCategoryLabel(
                                    item.failure_category
                                )}
                            </strong>
                            <span>
                                ${recovered} recovered /
                                ${total} cases
                            </span>
                        </div>

                        <div class="report-breakdown-value">
                            ${formatReportPercent(rate)}
                        </div>
                    </div>
                `;
            }
        );


        renderReportRows(
            "reportActionBreakdown",
            metrics.action_metrics,
            "No recovery-action metrics available.",
            function (item) {
                const actions =
                    Number(item.actions || 0);

                const executed =
                    Number(item.executed || 0);

                const blocked =
                    Number(item.blocked || 0);

                return `
                    <div class="report-breakdown-row" data-report-kind="action" data-report-item='${JSON.stringify(item)}'>
                        <div class="report-breakdown-main">
                            <strong>
                                ${reportActionLabel(
                                    item.action_type
                                )}
                            </strong>
                            <span>
                                ${actions} actions
                                &middot;
                                ${executed} executed
                                &middot;
                                ${blocked} blocked
                            </span>
                        </div>

                        <div class="report-breakdown-value">
                            ${actions}
                        </div>
                    </div>
                `;
            }
        );


        setText(
            "reportBlockedCases",
            String(
                Number(metrics.blocked_count || 0)
            )
        );

        setText(
            "reportGuardrailBlocks",
            String(
                Number(metrics.guardrail_blocks || 0)
            )
        );

        setText(
            "reportManualReviews",
            String(
                Number(metrics.manual_review_count || 0)
            )
        );


        bindReportBreakdownInteractions();

        const reportMeta =
            document.querySelector(
                ".report-header-meta"
            );

        if (reportMeta) {
            reportMeta.dataset.batchId =
                metrics.batch_id ||
                DEFAULT_BATCH;
        }
    }


    function initializeReportsDashboard() {
        const refreshButton =
            document.getElementById(
                "refreshReportBtn"
            );

        if (
            refreshButton &&
            !refreshButton.dataset.bound
        ) {
            refreshButton.addEventListener(
                "click",
                function () {
                    refreshButton.disabled = true;
                    refreshButton.textContent =
                        "REFRESHING...";

                    refreshMetrics(
                        getSelectedBatchId() ||
                        DEFAULT_BATCH
                    )
                        .then(function (metrics) {
                            renderReportDashboard(
                                metrics
                            );

                            clearReportSelection();
                        })
                        .catch(function (error) {
                            console.error(
                                "DunnFlow report refresh failed:",
                                error
                            );
                        })
                        .finally(function () {
                            refreshButton.disabled = false;
                            refreshButton.innerHTML =
                                "&#8635;&nbsp; REFRESH";
                        });
                }
            );

            refreshButton.dataset.bound = "true";
        }

        const reportButton =
            document.getElementById(
                "downloadReportBtn"
            );

        if (
            reportButton &&
            !reportButton.dataset.bound
        ) {
            reportButton.addEventListener(
                "click",
                function () {
                    try {
                        const batchId =
                            getSelectedBatchId() ||
                            DEFAULT_BATCH;

                        window.location.href =
                            getReportUrl(batchId);

                    } catch (error) {
                        console.error(
                            "DunnFlow report download failed:",
                            error
                        );
                    }
                }
            );

            reportButton.dataset.bound = "true";
        }

        refreshMetrics(
            getSelectedBatchId() ||
            DEFAULT_BATCH
        )
            .then(function (metrics) {
                renderReportDashboard(
                    metrics
                );
            })
            .catch(function (error) {
                console.error(
                    "DunnFlow reports dashboard initialization failed:",
                    error
                );
            });
    }

    /*
     * ------------------------------------------------------------------
     * Existing Razorpay order checkout
     * ------------------------------------------------------------------
     *
     * This is intentionally separate from recovery execution.
     * It opens an already-created Razorpay Test Mode order.
     * It does NOT create a new order or execute recovery.
     */

    async function openExistingRazorpayCheckout(batchId) {
        const response = await fetch(
            `/api/batches/${encodeURIComponent(batchId)}/razorpay-checkout`
        );

        if (!response.ok) {
            let detail = "No existing Razorpay Checkout order found.";

            try {
                const errorBody = await response.json();
                if (errorBody && errorBody.detail) {
                    detail = errorBody.detail;
                }
            } catch (error) {
                // Keep the safe default detail.
            }

            throw new Error(detail);
        }

        const checkout = await response.json();

        if (!window.Razorpay) {
            throw new Error(
                "Razorpay Checkout SDK is not loaded."
            );
        }

        if (
            window.DunnFlowLiveFeed &&
            typeof window.DunnFlowLiveFeed.add === "function"
        ) {
            window.DunnFlowLiveFeed.add(
                "Opening Razorpay Checkout for existing recovery order...",
                "info"
            );
        }

        const options = {
            key: checkout.razorpay_key_id,
            amount: checkout.amount,
            currency: checkout.currency || "INR",
            name: "DunnFlow",
            description: "Subscription revenue recovery",
            order_id: checkout.razorpay_order_id,

            handler: async function (response) {
                console.log(
                    "Razorpay Checkout success:",
                    response
                );

                if (
                    window.DunnFlowLiveFeed &&
                    typeof window.DunnFlowLiveFeed.add === "function"
                ) {
                    window.DunnFlowLiveFeed.add(
                        "Customer payment submitted. Waiting for Razorpay confirmation...",
                        "info"
                    );
                }

                updatePipeline(
                    "outcome",
                    "awaiting"
                );

                setText(
                    "outcomeResult",
                    "AWAITING PAYMENT"
                );

                /*
                 * Razorpay Checkout success means the payment was submitted
                 * successfully by the customer. DunnFlow only marks recovery
                 * VERIFIED after the existing backend reconciliation path
                 * has processed the Razorpay webhook and updated the invoice.
                 *
                 * Do not manufacture a successful state in the browser.
                 */
                const batchId =
                    getSelectedBatchId() ||
                    DEFAULT_BATCH;

                const maxAttempts = 15;
                const pollDelayMs = 2000;

                for (
                    let attempt = 0;
                    attempt < maxAttempts;
                    attempt += 1
                ) {
                    await new Promise(
                        function (resolve) {
                            setTimeout(
                                resolve,
                                pollDelayMs
                            );
                        }
                    );

                    const metrics =
                        await refreshMetrics(
                            batchId
                        );

                    if (!metrics) {
                        continue;
                    }

                    DunnFlowState.lastMetrics =
                        metrics;

                    /*
                     * get_batch_metrics() exposes financial truth through
                     * recovery_confirmed events and the resulting
                     * recovered_count. It does not return an invoices array.
                     */
                    const recoveredCount =
                        Number(
                            metrics.recovered_count ||
                            0
                        );

                    const amountRecovered =
                        Number(
                            metrics.amount_recovered ||
                            0
                        );

                    const recoveryConfirmed =
                        recoveredCount > 0 &&
                        amountRecovered > 0;

                    if (
                        recoveryConfirmed
                    ) {
                        DunnFlowState.demoStage =
                            "completed";

                        updatePipeline(
                            "outcome",
                            "success"
                        );

                        setText(
                            "outcomeResult",
                            "VERIFIED"
                        );

                        if (
                            window.DunnFlowLiveFeed &&
                            typeof window.DunnFlowLiveFeed.add === "function"
                        ) {
                            window.DunnFlowLiveFeed.add(
                                "Recovery verified: Razorpay payment captured and invoice settled.",
                                "success"
                            );
                        }

                        try {
                            renderCases(
                                await getDemoCases(
                                    batchId
                                )
                            );
                        } catch (error) {
                            console.warn(
                                "DunnFlow case refresh after Razorpay payment failed:",
                                error
                            );
                        }

                        return;
                    }
                }

                /*
                 * The payment was submitted, but the webhook/reconciliation
                 * has not completed within the polling window.
                 * Keep the state honest instead of showing VERIFIED.
                 */
                updatePipeline(
                    "outcome",
                    "awaiting"
                );

                setText(
                    "outcomeResult",
                    "AWAITING CONFIRMATION"
                );

                if (
                    window.DunnFlowLiveFeed &&
                    typeof window.DunnFlowLiveFeed.add === "function"
                ) {
                    window.DunnFlowLiveFeed.add(
                        "Payment submitted. Waiting for Razorpay webhook confirmation.",
                        "info"
                    );
                }
            },

            modal: {
                ondismiss: function () {
                    if (
                        window.DunnFlowLiveFeed &&
                        typeof window.DunnFlowLiveFeed.add === "function"
                    ) {
                        window.DunnFlowLiveFeed.add(
                            "Razorpay Checkout was closed before payment.",
                            "warning"
                        );
                    }
                }
            }
        };

        const razorpay = new Razorpay(options);
        razorpay.open();
    }


    /*
     * ------------------------------------------------------------------
     * RUN RECOVERY button binding
     * ------------------------------------------------------------------
     *
     * The recovery pipeline already exists in runRecovery().
     * This initializer only connects the UI button to that pipeline.
     */
    function initializeRunRecoveryButton() {
        const button =
            document.getElementById(
                "runBatchBtn"
            );

        if (
            !button ||
            button.dataset.recoveryBound === "true"
        ) {
            return;
        }

        button.addEventListener(
            "click",
            async function () {
                try {
                    await runRecovery();
                } catch (error) {
                    console.error(
                        "DunnFlow RUN RECOVERY button error:",
                        error
                    );
                }
            }
        );

        button.dataset.recoveryBound = "true";
    }



    function initializeExistingRazorpayCheckout() {
        const button =
            document.getElementById(
                "payExistingOrderBtn"
            );

        if (
            !button ||
            button.dataset.bound === "true"
        ) {
            return;
        }

        button.addEventListener(
            "click",
            async function () {
                const batchId =
                    getSelectedBatchId() ||
                    DEFAULT_BATCH;

                try {
                    button.disabled = true;
                    button.textContent =
                        "OPENING CHECKOUT...";

                    await openExistingRazorpayCheckout(
                        batchId
                    );

                } catch (error) {
                    console.error(
                        "Existing Razorpay Checkout error:",
                        error
                    );

                    if (
                        window.DunnFlowLiveFeed &&
                        typeof window.DunnFlowLiveFeed.error === "function"
                    ) {
                        window.DunnFlowLiveFeed.error(
                            `Unable to open existing Razorpay Checkout: ${error.message}`
                        );
                    }

                } finally {
                    button.disabled = false;
                    button.textContent =
                        "PAY EXISTING ORDER";
                }
            }
        );

        button.dataset.bound = "true";
    }


    window.DunnFlowMetrics = {
        refresh:
            refreshMetrics,

        renderMetrics,

        renderReportDashboard,

        renderCases,

        runRecovery,

        runControlRecovery,

        runDemoRecovery,

        inspectSelectedDemoCase,

        resetPipeline
    };


    /*
     * ------------------------------------------------------------------
     * Initialization
     * ------------------------------------------------------------------
     */

    function initialize() {
        initializeBatchState();

        initializeRunRecoveryButton();

        initializeReportsDashboard();

        initializeExistingRazorpayCheckout();

        resetPipeline();

        initializeMetrics();
    }


    if (
        document.readyState ===
        "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            initialize,
            { once: true }
        );
    } else {
        initialize();
    }
})();