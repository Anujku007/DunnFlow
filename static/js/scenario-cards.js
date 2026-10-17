
async function refreshRecoveryAgent(batchId) {
    if (
        !batchId ||
        !window.DunnFlowAPI ||
        typeof window.DunnFlowAPI.getRecoveryAgent !== "function"
    ) {
        return;
    }

    try {
        const payload =
            await window.DunnFlowAPI.getRecoveryAgent(
                batchId
            );

        if (window.DunnFlowState) {
            DunnFlowState.agentState =
                payload &&
                payload.agent
                    ? payload.agent.state || "idle"
                    : "idle";

            DunnFlowState.agentReady =
                Boolean(
                    payload &&
                    payload.agent &&
                    payload.agent.agent_ready
                );

            DunnFlowState.agentHistory =
                payload &&
                payload.agent &&
                Array.isArray(payload.agent.history)
                    ? payload.agent.history
                    : [];

            DunnFlowState.agentPlan = payload;
        }

        document.dispatchEvent(
            new CustomEvent(
                "dunnflow:agent-ready",
                {
                    detail: payload
                }
            )
        );

        return payload;
    } catch (error) {
        console.warn(
            "DunnFlow agent inspection failed:",
            error
        );

        if (window.DunnFlowState) {
            DunnFlowState.agentState = "unavailable";
            DunnFlowState.agentReady = false;
            DunnFlowState.agentHistory = [];
            DunnFlowState.agentPlan = null;
        }

        return null;
    }
}

/*
 * DunnFlow â€” Demo Scenario Cards
 *
 * Responsibilities:
 * - Define the three judge-facing demo scenarios.
 * - Handle Demo Lab card selection.
 * - Enter demo mode through DunnFlowState.
 *
 * IMPORTANT:
 * - This file does NOT execute recovery.
 * - This file does NOT call the backend.
 * - This file does NOT modify the batch selector.
 * - Navigation state does not affect scenario selection.
 */

(function () {
    "use strict";


    const DEMO_SCENARIOS = {
        fresh: {
            key: "fresh",

            invoiceId:
                "inv_dunnflow_006",

            label:
                "Insufficient Funds â€” Fresh Demo",

            failureCategory:
                "insufficient_funds",

            expectedAction:
                "retry_payment"
        },

        guardrail: {
            key: "guardrail",

            invoiceId:
                "inv_dunnflow_012",

            label:
                "Insufficient Funds â€” Guardrail Demo",

            failureCategory:
                "insufficient_funds",

            expectedAction:
                "retry_payment"
        },

        manualReview: {
            key: "manualReview",

            invoiceId:
                "inv_dunnflow_060",

            label:
                "Unclassified â€” Manual Review",

            failureCategory:
                "unclassified",

            expectedAction:
                "manual_review"
        },

        successfulRecovery: {
            key: "successfulRecovery",

            invoiceId:
                "inv_dunnflow_030",

            label:
                "Bank Timeout - Successful Recovery",

            failureCategory:
                "bank_timeout",

            expectedAction:
                "auto_retry_same_card"
        },
        razorpayVideoDemo: {
            key: "razorpayVideoDemo",

            invoiceId:
                "razorpay_fresh_session_pending",

            label:
                "Razorpay Test Mode ? ?299 Recovery",

            failureCategory:
                "insufficient_funds",

            expectedAction:
                "retry_payment"
        }
    };


    /**
     * Find the scenario represented by a card.
     */
    function getScenarioFromCard(card) {
        if (!card) {
            return null;
        }

        const invoiceId =
            card.dataset.invoice ||
            card.dataset.invoiceId ||
            null;

        if (!invoiceId) {
            return null;
        }

        return (
            Object.values(DEMO_SCENARIOS)
                .find(
                    (scenario) =>
                        scenario.invoiceId ===
                        invoiceId
                ) ||
            null
        );
    }


    /**
     * Clear selected state from all cards.
     */
    function clearCardSelection() {
        document
            .querySelectorAll(".scenario-card")
            .forEach((card) => {
                card.classList.remove(
                    "is-selected"
                );

                card.setAttribute(
                    "aria-selected",
                    "false"
                );
            });
    }


    /**
     * Visually select one card.
     */
    function selectCard(card) {
        if (!card) {
            return;
        }

        clearCardSelection();

        card.classList.add(
            "is-selected"
        );

        card.setAttribute(
            "aria-selected",
            "true"
        );
    }


    /**
     * Reset the visible recovery result area
     * when the user selects a different scenario.
     */
    function resetDemoPresentation() {
        const selectors = [
            "#diagnosisResult",
            "#decisionResult",
            "#executionResult",
            "#outcomeResult"
        ];

        selectors.forEach((selector) => {
            const element =
                document.querySelector(selector);

            if (!element) {
                return;
            }

            /*
             * Do not destroy the surrounding DOM.
             * Only clear text that may have been
             * populated by the recovery pipeline.
             */
            if (
                element.dataset &&
                element.dataset.dunnflowDynamic ===
                    "true"
            ) {
                element.textContent = "";
            }
        });
    }


    /**
     * Refresh the visible audit trail for the current UI context.
     *
     * This is read-only presentation work.
     * It does not diagnose, decide, schedule, or execute recovery.
     */
    function refreshAuditContext({
        invoiceId = null,
        batchId = null
    } = {}) {
        if (
            !window.DunnFlowAudit ||
            typeof window.DunnFlowAudit.load !==
                "function"
        ) {
            return;
        }

        window.DunnFlowAudit
            .load({
                invoiceId,
                batchId
            })
            .catch(function (error) {
                console.warn(
                    "DunnFlow audit refresh failed:",
                    error
                );
            });
    }


        let syntheticDemoRunPromise = null;

    /**
     * Create one isolated synthetic run per browser page session.
     * This only creates fixture data; it never executes recovery.
     */
    async function ensureSyntheticDemoRun() {
        const state = window.DunnFlowState;

        if (
            state &&
            state.runId &&
            state.demoScenarioCards
        ) {
            return {
                run_id: state.runId,
                batch_id: state.demoRunBatchId,
                scenario_cards: state.demoScenarioCards
            };
        }

        if (
            !window.DunnFlowAPI ||
            typeof window.DunnFlowAPI.createDemoRun !== "function"
        ) {
            throw new Error(
                "Demo run API is unavailable. Reload the page after updating api.js."
            );
        }

        if (!syntheticDemoRunPromise) {
            syntheticDemoRunPromise =
                window.DunnFlowAPI.createDemoRun()
                    .then(function (run) {
                        if (
                            !run ||
                            !run.run_id ||
                            !run.batch_id ||
                            !run.scenario_cards
                        ) {
                            throw new Error(
                                "The server returned an incomplete demo run."
                            );
                        }

                        if (state) {
                            state.runId = run.run_id;
                            state.demoRunBatchId = run.batch_id;
                            state.demoScenarioCards = run.scenario_cards;
                        }

                        return run;
                    })
                    .finally(function () {
                        syntheticDemoRunPromise = null;
                    });
        }

        return syntheticDemoRunPromise;
    }

/**
     * Handle a Demo Lab card click.
     */
    // DUNNFLOW_SELECTION_GENERATION_GUARD
    // Invalidates asynchronous work from an older card selection.
    let scenarioSelectionGeneration = window.__dunnflowScenarioSelectionGeneration || 0;

    async function handleCardClick(event) {
        const clickGeneration = ++scenarioSelectionGeneration;
        window.__dunnflowScenarioSelectionGeneration = scenarioSelectionGeneration;
        const card =
            event.currentTarget;

        const scenario =
            getScenarioFromCard(card);

        if (!scenario) {
            console.warn(
                "DunnFlow: unknown demo scenario.",
                card
            );

            return;
        }

        /*
         * Toggle the selected Demo Lab scenario.
         *
         * Clicking an unselected card selects it.
         * Clicking the already-selected card clears
         * the selection and returns the UI to
         * Control Center mode.
         */
        const wasSelected =
            card.classList.contains(
                "is-selected"
            );

        if (
            typeof enterDemoMode !==
                "function" ||
            typeof enterControlMode !==
                "function"
        ) {
            console.error(
                "DunnFlow: state.js is not loaded."
            );

            return;
        }

        resetDemoPresentation();

        if (wasSelected) {
            clearCardSelection();

            const batchId =
                getSelectedBatchId();

            enterControlMode(
                batchId
            );

            updateExistingOrderButton(
                batchId
            );

            refreshAuditContext({
                batchId
            });

            document.dispatchEvent(
                new CustomEvent(
                    "dunnflow:demo-selected",
                    {
                        detail: {
                            scenario: null,
                            invoiceId: null
                        }
                    }
                )
            );

            return;
        }

        /*
         * Scenario selection changes only the recovery target.
         *
         * The selected Demo Batch belongs to the batch selector
         * and must remain untouched.
         */
                let selectedScenario = scenario;

        /*
         * Synthetic scenarios use invoices from this visitor's
         * isolated 60-case run, never the reference benchmark.
         * The Razorpay card is intentionally left for its separate
         * fresh-order integration patch.
         */
        if (scenario.key !== "razorpayVideoDemo") {
            let run;

            try {
                run = await ensureSyntheticDemoRun();
                if (clickGeneration !== scenarioSelectionGeneration) {
                    return;
                }
            } catch (error) {
                console.error(
                    "DunnFlow could not create an isolated demo run:",
                    error
                );
                window.alert(
                    "Could not prepare an isolated demo run. Please reload and try again."
                );
                return;
            }

            const scenarioKeyMap = {
                fresh: "fresh",
                guardrail: "guardrail",
                manualReview: "manual_review",
                successfulRecovery: "successful_recovery"
            };

            const serverScenarioKey =
                scenarioKeyMap[scenario.key];

            const isolatedInvoiceId =
                serverScenarioKey
                    ? run.scenario_cards[serverScenarioKey]
                    : null;

            if (!isolatedInvoiceId) {
                console.error(
                    "DunnFlow: the isolated run has no invoice for scenario:",
                    scenario.key
                );
                window.alert(
                    "This scenario is not available in the isolated demo run."
                );
                return;
            }

            selectedScenario = {
                ...scenario,
                invoiceId: isolatedInvoiceId
            };
        }

        if (clickGeneration !== scenarioSelectionGeneration) {
            return;
        }

        enterDemoMode(
            selectedScenario.invoiceId,
            selectedScenario
        );

        /*
         * Scenario selection is target selection only.
         *
         * No detection, decision, execution, or AI inspection
         * is allowed to run here.
         */
        if (
            window.DunnFlowMetrics &&
            typeof window.DunnFlowMetrics.resetPipeline ===
                "function"
        ) {
            window.DunnFlowMetrics.resetPipeline();
        }

        selectCard(card);

        /*
         * Tell other UI components that the
         * selected Demo Lab case changed.
         */
        refreshAuditContext({ invoiceId: selectedScenario.invoiceId });

        document.dispatchEvent(
            new CustomEvent(
                "dunnflow:demo-selected",
                {
                    detail: { scenario: selectedScenario, invoiceId: selectedScenario.invoiceId }
                }
            )
        );
        // Prepare a fresh isolated Test Mode session after card selection.
        // This does not open Checkout or execute recovery.
        if (selectedScenario.key === "razorpayVideoDemo") {
            if (!window.DunnFlowMetrics ||
                typeof window.DunnFlowMetrics.prepareIsolatedRazorpayDemoSession !== "function") {
                console.error("DunnFlow: isolated Razorpay session preparation is unavailable.");
                if (window.DunnFlowLiveFeed &&
                    typeof window.DunnFlowLiveFeed.error === "function") {
                    window.DunnFlowLiveFeed.error(
                        "Razorpay session preparation is unavailable. Reload the page and try again."
                    );
                }
                return;
            }

            try {
                await window.DunnFlowMetrics.prepareIsolatedRazorpayDemoSession();
            } catch (error) {
                console.error(
                    "DunnFlow: could not prepare the isolated Razorpay demo session:",
                    error
                );
                if (window.DunnFlowLiveFeed &&
                    typeof window.DunnFlowLiveFeed.error === "function") {
                    window.DunnFlowLiveFeed.error(
                        "Could not prepare Razorpay Test Mode session: " + error.message
                    );
                }
            }
        }


    }


    /**
     * Handle batch selector changes.
     *
     * Batch selection owns the dashboard metrics and
     * returns the UI to Control Center mode.
     */
    function handleBatchChange(event) {
        const batchId =
            event &&
            event.target
                ? event.target.value
                : DUNNFLOW_DEFAULT_BATCH;

        clearCardSelection();

        enterControlMode(
            batchId
        );

        updateExistingOrderButton(
            batchId
        );

        if (
            window.DunnFlowMetrics &&
            typeof window.DunnFlowMetrics.resetPipeline ===
                "function"
        ) {
            window.DunnFlowMetrics.resetPipeline();
        }

        document.dispatchEvent(
            new CustomEvent(
                "dunnflow:demo-selected",
                {
                    detail: {
                        scenario: null,
                        invoiceId: null
                    }
                }
            )
        );

        refreshAuditContext({
            batchId
        });

        // The dunnflow:demo-selected listener in metrics.js refreshes
        // the selected batch once after the context switch.
    }


    /**
     * Handle batch selector changes.
     *
     * Selecting a batch means the user is working
     * in Control Center mode.
     */
        /**
     * Show the existing Razorpay checkout control only
     * for Razorpay-specific batches.
     */
    function updateExistingOrderButton(batchId) {
        const button =
            document.getElementById(
                "payExistingOrderBtn"
            );

        const caption =
            document.querySelector(
                ".run-recovery-caption"
            );

        if (!button) {
            return;
        }

        const isRazorpayBatch =
            String(batchId || "").startsWith(
                "razorpay_"
            );

        button.hidden =
            !isRazorpayBatch;

        if (caption) {
            caption.hidden =
                !isRazorpayBatch;
        }
    }


    /**
     * Initialize Demo Lab cards.
     */
    function initScenarioCards() {
        const cards =
            document.querySelectorAll(
                ".scenario-card"
            );

        cards.forEach((card) => {
            card.setAttribute(
                "role",
                "button"
            );

            card.setAttribute(
                "tabindex",
                "0"
            );

            card.setAttribute(
                "aria-selected",
                "false"
            );

            card.addEventListener(
                "click",
                handleCardClick
            );

            card.addEventListener(
                "keydown",
                (event) => {
                    if (
                        event.key ===
                            "Enter" ||
                        event.key ===
                            " "
                    ) {
                        event.preventDefault();

                        handleCardClick(event);
                    }
                }
            );
        });


        const batchSelect =
            document.getElementById(
                "batchSelect"
            );

        if (batchSelect) {
                        updateExistingOrderButton(
                batchSelect.value
            );

            batchSelect.addEventListener(
                "change",
                handleBatchChange
            );
        }
    }


    /**
     * Public Demo Lab contract.
     */
    window.DunnFlowDemo = {
    refreshRecoveryAgent,
        scenarios:
            DEMO_SCENARIOS,

        getScenarioFromCard,

        selectCard,

        clearSelection:
            clearCardSelection
    };


    if (
        document.readyState ===
        "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            initScenarioCards,
            { once: true }
        );
    } else {
        initScenarioCards();
    }
})();


