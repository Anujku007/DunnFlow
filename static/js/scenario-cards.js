/*
 * DunnFlow — Demo Scenario Cards
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
                "Insufficient Funds — Fresh Demo",

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
                "Insufficient Funds — Guardrail Demo",

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
                "Unclassified — Manual Review",

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
                "inv_dunnflow_001",

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
     * Handle a Demo Lab card click.
     */
    function handleCardClick(event) {
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
        enterDemoMode(
            scenario.invoiceId,
            scenario.key
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
        document.dispatchEvent(
            new CustomEvent(
                "dunnflow:demo-selected",
                {
                    detail: {
                        scenario,
                        invoiceId:
                            scenario.invoiceId
                    }
                }
            )
        );
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

        if (
            window.DunnFlowMetrics &&
            typeof window.DunnFlowMetrics.refresh ===
                "function"
        ) {
            window.DunnFlowMetrics
                .refresh(batchId);
        }
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