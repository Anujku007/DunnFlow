/*
 * DunnFlow — Live Recovery Feed
 *
 * Responsibilities:
 * - Render recovery activity in the live feed.
 * - Provide small helpers for pipeline status messages.
 *
 * IMPORTANT:
 * - No API calls.
 * - No recovery execution.
 * - No frontend mode changes.
 * - No business decisions.
 */

(function () {
    "use strict";


    const FEED_SELECTOR =
        "#activityFeed";


    /**
     * Return the live-feed container.
     */
    function getFeedElement() {
        return document.querySelector(
            FEED_SELECTOR
        );
    }


    /**
     * Clear the live feed.
     */
    function clearFeed() {
        const feed =
            getFeedElement();

        if (!feed) {
            return;
        }

        feed.innerHTML = "";
    }


    /**
     * Create one feed item.
     */
    function createFeedItem(
        message,
        type = "info"
    ) {
        const item =
            document.createElement("div");

        item.className =
            "activity-item";

        item.dataset.type =
            type;

        const timestamp =
            document.createElement("span");

        timestamp.className =
            "activity-time";

        timestamp.textContent =
            new Date().toLocaleTimeString(
                [],
                {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit"
                }
            );


        const content =
            document.createElement("span");

        content.className =
            "activity-message";

        content.textContent =
            message;


        item.appendChild(timestamp);
        item.appendChild(content);

        return item;
    }


    /**
     * Add an activity message to the feed.
     */
    function addFeedItem(
        message,
        type = "info"
    ) {
        if (
            message === null ||
            message === undefined
        ) {
            return;
        }

        const feed =
            getFeedElement();

        if (!feed) {
            return;
        }

        const item =
            createFeedItem(
                String(message),
                type
            );

        /*
         * Newest event appears first.
         */
        feed.prepend(item);
    }


    /**
     * Add a pipeline status event.
     */
    function addPipelineEvent(
        stage,
        message,
        type = "info"
    ) {
        const prefix =
            stage
                ? `${stage}: `
                : "";

        addFeedItem(
            `${prefix}${message}`,
            type
        );
    }


    /**
     * Add a recovery-start event.
     */
    function recoveryStarted(
        label = "Recovery started"
    ) {
        addFeedItem(
            label,
            "info"
        );
    }


    /**
     * Add diagnosis event.
     */
    function diagnosisCompleted(
        category
    ) {
        addPipelineEvent(
            "Diagnosis",
            category
                ? `Failure classified as ${category}.`
                : "Failure diagnosis completed.",
            "info"
        );
    }


    /**
     * Add deterministic decision event.
     */
    function decisionCompleted(
        action
    ) {
        addPipelineEvent(
            "Decision",
            action
                ? `Deterministic action: ${action}.`
                : "Deterministic decision completed.",
            "info"
        );
    }


    /**
     * Add successful recovery event.
     */
    function recoveryVerified(
        amount
    ) {
        let message =
            "Recovery verified.";

        if (
            typeof amount === "number" &&
            Number.isFinite(amount)
        ) {
            message =
                `Recovery verified: ₹${(
                    amount / 100
                ).toLocaleString(
                    "en-IN",
                    {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2
                    }
                )} recovered.`;
        }

        addFeedItem(
            message,
            "success"
        );
    }


    /**
     * Add guardrail-block event.
     */
    function recoveryBlocked(
        reason
    ) {
        addFeedItem(
            reason
                ? `Recovery blocked: ${reason}`
                : "Recovery blocked by deterministic guardrail.",
            "warning"
        );
    }


    /**
     * Add manual-review event.
     */
    function manualReview(
        reason
    ) {
        addFeedItem(
            reason
                ? `Manual review required: ${reason}`
                : "Manual review required. Automatic execution stopped.",
            "warning"
        );
    }


    /**
     * Add generic error event.
     */
    function recoveryError(
        message
    ) {
        addFeedItem(
            message
                ? `Recovery error: ${message}`
                : "Recovery encountered an error.",
            "error"
        );
    }


    /**
     * Public live-feed contract.
     */
    window.DunnFlowLiveFeed = {
        clear: clearFeed,

        add: addFeedItem,

        pipeline:
            addPipelineEvent,

        recoveryStarted,

        diagnosisCompleted,

        decisionCompleted,

        recoveryVerified,

        recoveryBlocked,

        manualReview,

        error:
            recoveryError
    };
})();