(function () {
    "use strict";

    // Drag-and-drop reordering for the dashboard Person cards.
    // The arrow buttons keep working without JavaScript; this script
    // only adds dragging and submits the complete new order.

    var grid = document.querySelector("[data-person-grid]");
    var orderForm = document.getElementById("person-order-form");

    if (!grid || !orderForm) {
        return;
    }

    var cards = Array.prototype.slice.call(
        grid.querySelectorAll("[data-person-id]")
    );

    if (cards.length < 2) {
        return;
    }

    var hint = document.querySelector("[data-person-order-hint]");

    if (hint) {
        hint.hidden = false;
    }

    var draggedCard = null;
    var initialOrder = currentOrder();

    function currentOrder() {
        return Array.prototype.map.call(
            grid.querySelectorAll("[data-person-id]"),
            function (card) {
                return card.getAttribute("data-person-id");
            }
        ).join(",");
    }

    function cardAfterPointer(x, y) {
        var candidates = Array.prototype.slice.call(
            grid.querySelectorAll("[data-person-id]:not(.is-dragging)")
        );

        for (var i = 0; i < candidates.length; i += 1) {
            var box = candidates[i].getBoundingClientRect();
            var sameRow = y >= box.top && y <= box.bottom;

            if (y < box.top || (sameRow && x < box.left + box.width / 2)) {
                return candidates[i];
            }
        }

        return null;
    }

    cards.forEach(function (card) {
        card.setAttribute("draggable", "true");
        card.classList.add("is-draggable");

        card.addEventListener("dragstart", function (event) {
            draggedCard = card;
            card.classList.add("is-dragging");
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData(
                "text/plain",
                card.getAttribute("data-person-id")
            );
        });

        card.addEventListener("dragend", function () {
            card.classList.remove("is-dragging");
            draggedCard = null;

            var newOrder = currentOrder();

            if (newOrder !== initialOrder) {
                orderForm.elements.person_ids.value = newOrder;
                grid.classList.add("is-saving");
                orderForm.submit();
            }
        });
    });

    grid.addEventListener("dragover", function (event) {
        if (!draggedCard) {
            return;
        }

        event.preventDefault();
        event.dataTransfer.dropEffect = "move";

        var nextCard = cardAfterPointer(event.clientX, event.clientY);

        if (nextCard === null) {
            grid.appendChild(draggedCard);
        } else if (nextCard !== draggedCard.nextElementSibling) {
            grid.insertBefore(draggedCard, nextCard);
        }
    });

    grid.addEventListener("drop", function (event) {
        event.preventDefault();
    });
})();
