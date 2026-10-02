
(function () {
    "use strict";

    function byId(id) {
        return document.getElementById(id);
    }

    function openModal() {
        const modal = byId("decisionIntelligenceModal");

        if (!modal) {
            return;
        }

        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("decision-modal-open");

        const closeButton = byId("closeDecisionModalBtn");

        if (closeButton) {
            closeButton.focus();
        }
    }

    function closeModal() {
        const modal = byId("decisionIntelligenceModal");

        if (!modal) {
            return;
        }

        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("decision-modal-open");

        const trigger = byId("inspectDecisionBtn");

        if (trigger) {
            trigger.focus();
        }
    }

    function init() {
        const trigger = byId("inspectDecisionBtn");
        const closeButton = byId("closeDecisionModalBtn");
        const modal = byId("decisionIntelligenceModal");

        if (!trigger || !closeButton || !modal) {
            return;
        }

        trigger.addEventListener(
            "click",
            async function () {
                const invoiceId =
                    window.DunnFlowState &&
                    window.DunnFlowState.invoiceId;

                /*
                 * Explicitly inspect the selected case.
                 *
                 * This is read-only. It does not execute recovery
                 * and does not advance the visual pipeline.
                 */
                if (
                    invoiceId &&
                    window.DunnFlowMetrics &&
                    typeof window.DunnFlowMetrics
                        .inspectSelectedDemoCase ===
                        "function"
                ) {
                    const originalText =
                        trigger.textContent;

                    trigger.disabled = true;
                    trigger.textContent =
                        "INSPECTING AI...";

                    try {
                        await window.DunnFlowMetrics
                            .inspectSelectedDemoCase(
                                invoiceId
                            );
                    } catch (error) {
                        console.error(
                            "DunnFlow AI inspection failed:",
                            error
                        );
                    } finally {
                        trigger.disabled = false;
                        trigger.textContent =
                            originalText;
                    }
                }

                openModal();
            }
        );
        closeButton.addEventListener("click", closeModal);

        modal.addEventListener("click", function (event) {
            if (
                event.target &&
                event.target.dataset &&
                event.target.dataset.closeDecisionModal === "true"
            ) {
                closeModal();
            }
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                closeModal();
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    window.DunnFlowDecisionIntelligence = {
        open: openModal,
        close: closeModal
    };
})();
