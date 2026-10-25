(function () {
    "use strict";

    // Person page: the time-period filter and the champion history
    // dialog. The filter form works without JavaScript; this script
    // only hides the custom dates until they are needed. Choosing a
    // period does not submit by itself, because arrow keys change a
    // closed select one option at a time.

    var SERIES_COLORS = [
        "#60a5fa",
        "#4ade80",
        "#fbbf24",
        "#f472b6",
        "#a78bfa",
        "#2dd4bf"
    ];

    var dateFormatter = new Intl.DateTimeFormat(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric"
    });

    var numberFormatter = new Intl.NumberFormat(undefined);

    function setUpPeriodFilter() {
        var form = document.querySelector("[data-period-filter]");

        if (!form) {
            return;
        }

        var select = form.querySelector("[data-period-select]");
        var dates = form.querySelector("[data-period-dates]");

        select.addEventListener("change", function () {
            dates.hidden = select.value !== "custom";
        });

        form.addEventListener("submit", function () {
            // Preset periods do not use the date fields.
            if (select.value !== "custom") {
                Array.prototype.forEach.call(
                    dates.querySelectorAll("input"),
                    function (input) {
                        input.disabled = true;
                    }
                );
            }
        });
    }

    function showLocalDates() {
        Array.prototype.forEach.call(
            document.querySelectorAll("time[data-local-date]"),
            function (element) {
                var value = new Date(element.getAttribute("datetime"));

                if (!isNaN(value.getTime())) {
                    element.textContent = dateFormatter.format(value);
                }
            }
        );
    }

    function setUpHistoryDialog() {
        var dialog = document.querySelector("[data-history-dialog]");

        if (!dialog || typeof window.Chart === "undefined") {
            return;
        }

        var title = dialog.querySelector("[data-history-title]");
        var status = dialog.querySelector("[data-history-status]");
        var canvas = dialog.querySelector("[data-history-chart]");
        var closeButton = dialog.querySelector("[data-history-close]");
        var chart = null;
        var requestNumber = 0;

        function destroyChart() {
            if (chart) {
                chart.destroy();
                chart = null;
            }
        }

        function buildDatasets(accounts) {
            return accounts
                .filter(function (account) {
                    return account.points.length > 0;
                })
                .map(function (account, index) {
                    var color = SERIES_COLORS[index % SERIES_COLORS.length];

                    return {
                        label: account.riot_id,
                        borderColor: color,
                        backgroundColor: color,
                        borderWidth: 2,
                        tension: 0,
                        data: account.points.map(function (point) {
                            return {
                                x: new Date(point.recorded_at).getTime(),
                                y: point.mastery_points,
                                level: point.mastery_level,
                                levelUp: point.level_up
                            };
                        }),
                        pointRadius: account.points.map(function (point) {
                            return point.level_up ? 7 : 3;
                        }),
                        pointHoverRadius: account.points.map(function (point) {
                            return point.level_up ? 9 : 5;
                        }),
                        pointStyle: account.points.map(function (point) {
                            return point.level_up ? "rectRot" : "circle";
                        })
                    };
                });
        }

        function renderChart(datasets) {
            destroyChart();

            chart = new window.Chart(canvas, {
                type: "line",
                data: {
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    interaction: {
                        mode: "nearest",
                        intersect: false
                    },
                    scales: {
                        x: {
                            type: "linear",
                            ticks: {
                                color: "#94a3b8",
                                maxTicksLimit: 6,
                                callback: function (value) {
                                    return dateFormatter.format(new Date(value));
                                }
                            },
                            grid: {
                                color: "rgba(148, 163, 184, 0.15)"
                            }
                        },
                        y: {
                            beginAtZero: false,
                            ticks: {
                                color: "#94a3b8",
                                callback: function (value) {
                                    return numberFormatter.format(value);
                                }
                            },
                            grid: {
                                color: "rgba(148, 163, 184, 0.15)"
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            labels: {
                                color: "#cbd5e1"
                            }
                        },
                        tooltip: {
                            callbacks: {
                                title: function (items) {
                                    return items.length
                                        ? dateFormatter.format(new Date(items[0].raw.x))
                                        : "";
                                },
                                label: function (item) {
                                    var text = item.dataset.label + ": "
                                        + numberFormatter.format(item.raw.y)
                                        + " points";

                                    if (item.raw.level !== null) {
                                        text += ", level " + item.raw.level;
                                    }

                                    if (item.raw.levelUp) {
                                        text += " (level up)";
                                    }

                                    return text;
                                }
                            }
                        }
                    }
                }
            });
        }

        function openHistory(button) {
            var championName = button.getAttribute("data-champion-name");
            var currentRequest = requestNumber + 1;

            requestNumber = currentRequest;
            title.textContent = championName + " mastery history";
            status.textContent = "Loading history...";
            status.hidden = false;
            destroyChart();

            if (!dialog.open) {
                dialog.showModal();
            }

            fetch(button.getAttribute("data-history-url"), {
                headers: {
                    Accept: "application/json"
                }
            })
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error("History request failed.");
                    }

                    return response.json();
                })
                .then(function (history) {
                    if (currentRequest !== requestNumber || !dialog.open) {
                        return;
                    }

                    var datasets = buildDatasets(history.accounts);

                    if (!datasets.length) {
                        status.textContent = "No history yet for "
                            + championName
                            + ". It is recorded from the next sync onwards.";
                        return;
                    }

                    status.hidden = true;
                    renderChart(datasets);
                })
                .catch(function () {
                    if (currentRequest === requestNumber) {
                        status.textContent = "The history could not be loaded.";
                    }
                });
        }

        Array.prototype.forEach.call(
            document.querySelectorAll(".champion-history-button"),
            function (button) {
                button.addEventListener("click", function () {
                    openHistory(button);
                });
            }
        );

        closeButton.addEventListener("click", function () {
            dialog.close();
        });

        // Close when the backdrop outside the dialog box is clicked.
        dialog.addEventListener("click", function (event) {
            if (event.target === dialog) {
                dialog.close();
            }
        });

        dialog.addEventListener("close", destroyChart);
    }

    setUpPeriodFilter();
    showLocalDates();
    setUpHistoryDialog();
}());
