const wsProtocol = window.location.protocol === "https:" ? "wss://" : "ws://";
const wsUrl = wsProtocol + window.location.host + "/ws/alerts/";

function connectWebSocket() {
    console.log("Connecting to Alert WebSocket: " + wsUrl);
    const alertSocket = new WebSocket(wsUrl);

    alertSocket.onmessage = function (e) {
        try {
            const data = JSON.parse(e.data);
            if (data.type === "alert") {
                showToastNotification(data.stock, data.message, data.severity, data.timestamp);
                
                // Increment notification count indicator dynamically if present
                const badge = document.getElementById("alert-badge-count");
                if (badge) {
                    const currentCount = parseInt(badge.textContent || "0");
                    badge.textContent = currentCount + 1;
                    badge.classList.remove("d-none");
                }
            }
        } catch (err) {
            console.error("Error parsing WebSocket message: ", err);
        }
    };

    alertSocket.onclose = function (e) {
        console.warn("Alert WebSocket connection closed. Attempting reconnect in 10 seconds...");
        setTimeout(function () {
            connectWebSocket();
        }, 10000);
    };

    alertSocket.onerror = function (err) {
        console.error("WebSocket encountered error: ", err);
        alertSocket.close();
    };
}

connectWebSocket();

function showToastNotification(stock, message, severity, timestamp) {
    let container = document.getElementById("toast-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "toast-container";
        container.className = "toast-container position-fixed top-0 end-0 p-3";
        container.style.zIndex = "9999";
        document.body.appendChild(container);
    }

    // Class selection based on alert severity
    let headerClass = "bg-primary text-white";
    let iconClass = "bi-bell-fill";
    
    if (severity === "high") {
        headerClass = "bg-danger text-white";
        iconClass = "bi-exclamation-triangle-fill";
    } else if (severity === "medium") {
        headerClass = "bg-warning text-dark";
        iconClass = "bi-exclamation-circle-fill";
    }

    const toastId = "toast-" + Date.now();
    const toastHtml = `
        <div id="${toastId}" class="toast" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="toast-header ${headerClass}">
                <i class="bi ${iconClass} me-2"></i>
                <strong class="me-auto">${stock} Signal Alert</strong>
                <small>${timestamp || "Just Now"}</small>
                <button type="button" class="btn-close ${severity === "medium" ? "" : "btn-close-white"}" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
            <div class="toast-body" style="background-color: #1e293b; color: #f8fafc; border: 1px solid rgba(255,255,255,0.08);">
                ${message}
            </div>
        </div>
    `;

    container.insertAdjacentHTML("beforeend", toastHtml);

    const toastEl = document.getElementById(toastId);
    const bsToast = new bootstrap.Toast(toastEl, { delay: 12000 });
    bsToast.show();

    toastEl.addEventListener("hidden.bs.toast", function () {
        toastEl.remove();
    });
}
