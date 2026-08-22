(() => {
    "use strict";

    const bootstrapElement = document.getElementById(
        "league-mastery-tracker-tab-lifecycle"
    );

    if (!bootstrapElement) {
        return;
    }

    const csrfToken = (
        bootstrapElement.dataset.csrfToken || ""
    ).trim();

    const heartbeatUrl = (
        bootstrapElement.dataset.heartbeatUrl || ""
    ).trim();

    const closeUrl = (
        bootstrapElement.dataset.closeUrl || ""
    ).trim();

    if (
        !csrfToken
        || !heartbeatUrl
        || !closeUrl
    ) {
        return;
    }

    const heartbeatIntervalMilliseconds = 5000;

    let closeSignalSent = false;

    function createTabIdentifier() {
        if (
            window.crypto
            && typeof window.crypto.randomUUID === "function"
        ) {
            return window.crypto.randomUUID();
        }

        return [
            Date.now().toString(36),
            Math.random().toString(36).slice(2),
            Math.random().toString(36).slice(2),
        ].join("-");
    }

    const tabIdentifier = createTabIdentifier();

    function createRequestBody() {
        const formData = new FormData();

        formData.append(
            "tab_id",
            tabIdentifier
        );

        formData.append(
            "_csrf_token",
            csrfToken
        );

        return formData;
    }

    function createRequestHeaders() {
        return {
            "X-CSRF-Token": csrfToken,
        };
    }

    function sendHeartbeat() {
        fetch(
            heartbeatUrl,
            {
                method: "POST",
                body: createRequestBody(),
                credentials: "same-origin",
                cache: "no-store",
                headers: createRequestHeaders(),
            }
        ).catch(
            () => {
                /*
                 * A temporary failure is retried by the next
                 * scheduled heartbeat.
                 */
            }
        );
    }

    function sendCloseWithFetch() {
        fetch(
            closeUrl,
            {
                method: "POST",
                body: createRequestBody(),
                credentials: "same-origin",
                cache: "no-store",
                keepalive: true,
                headers: createRequestHeaders(),
            }
        ).catch(
            () => {
                /*
                 * sendBeacon is also attempted.
                 */
            }
        );
    }

    function sendCloseWithBeacon() {
        if (
            typeof navigator.sendBeacon
            !== "function"
        ) {
            return;
        }

        try {
            navigator.sendBeacon(
                closeUrl,
                createRequestBody()
            );
        } catch {
            /*
             * The keepalive fetch remains available.
             */
        }
    }

    function sendCloseSignal() {
        if (closeSignalSent) {
            return;
        }

        closeSignalSent = true;

        sendCloseWithFetch();
        sendCloseWithBeacon();
    }

    window.addEventListener(
        "pagehide",
        (event) => {
            if (event.persisted) {
                return;
            }

            sendCloseSignal();
        }
    );

    window.addEventListener(
        "beforeunload",
        () => {
            sendCloseSignal();
        }
    );

    window.addEventListener(
        "pageshow",
        () => {
            closeSignalSent = false;
            sendHeartbeat();
        }
    );

    document.addEventListener(
        "visibilitychange",
        () => {
            if (
                document.visibilityState
                === "visible"
            ) {
                closeSignalSent = false;
                sendHeartbeat();
            }
        }
    );

    sendHeartbeat();

    window.setInterval(
        sendHeartbeat,
        heartbeatIntervalMilliseconds
    );
})();