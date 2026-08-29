/* =========================================================
   SCENARIO CARD CONTROLS
   ---------------------------------------------------------
   Connects the visual scenario cards to the existing
   batch selector.

   Backend behavior is unchanged.
========================================================= */

document.addEventListener("DOMContentLoaded", () => {

    const scenarioCards =
        document.querySelectorAll(".scenario-card");

    const batchSelect =
        document.getElementById("batchSelect");


    if (!scenarioCards.length || !batchSelect) {
        return;
    }


    function updateSelectedCard(selectedCard) {

        scenarioCards.forEach(card => {
            card.classList.remove("is-selected");
        });

        if (selectedCard) {
            selectedCard.classList.add("is-selected");
        }
    }


    scenarioCards.forEach(card => {

        card.addEventListener("click", () => {

            const batchId =
                card.dataset.batch;

            if (!batchId) {
                return;
            }


            /*
             * Update the existing batch selector.
             */
            batchSelect.value = batchId;


            /*
             * Update the visual selected state immediately.
             */
            updateSelectedCard(card);


            /*
             * Trigger the SAME change event used by
             * the existing dropdown.
             *
             * This means we reuse handleBatchChange()
             * indirectly instead of duplicating API logic.
             */
            batchSelect.dispatchEvent(
                new Event("change", {
                    bubbles: true
                })
            );

        });

    });


    /*
     * Keep scenario cards synchronized if the user
     * changes the dropdown manually.
     */
    batchSelect.addEventListener("change", () => {

        const selectedBatch =
            batchSelect.value;

        const matchingCard =
            Array.from(scenarioCards).find(
                card =>
                    card.dataset.batch === selectedBatch
            );

        updateSelectedCard(matchingCard);

    });

});