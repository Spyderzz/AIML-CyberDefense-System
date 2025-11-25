// frontend/src/main.jsx
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./utils/automation"; // enables background mouse tracker

(function guardedInjectFlowReport() {
  try {
    if (typeof document === "undefined") return; 

    const ID = "flow-report-js";
    if (document.getElementById(ID)) return; 

    // Vite environment detection (works in Vite)
    const isProd = (typeof import.meta !== "undefined" && import.meta.env && import.meta.env.PROD)
      || (typeof process !== "undefined" && process.env && process.env.NODE_ENV === "production");

    // If you run backend at a different host/port, add it to this list.
    const likelyBackendPorts = new Set(["5000", "8000", "8080"]); 
    const currentPort = window.location.port || "";
    const originIsBackendPort = likelyBackendPorts.has(currentPort);

    // If host is not the dev server (3000) or port looks like a backend, allow injection in dev too.
    const runningOnViteDevServer = currentPort === "3000" || /:3000$/.test(window.location.origin);
    const originLooksLikeBackend = originIsBackendPort || window.location.hostname === "127.0.0.1" && currentPort === "5000";

    // Decision: inject only when production OR origin looks like backend (so backend-served pages still get it)
    if (!isProd && runningOnViteDevServer && !originLooksLikeBackend) {
      // DEV on Vite: skip injection to avoid noisy 404 / CSP / eval warnings
      return;
    }

    const scriptSrc = window.__FLOW_COLLECTOR_ENDPOINT__ || "/static/flow_report.js";

    const script = document.createElement("script");
    script.id = ID;
    script.src = scriptSrc;
    script.defer = true;
    script.async = true;
    script.crossOrigin = "anonymous";

    script.onload = () => {
      try {
        if (window && window.console && window.console.debug) {
          console.debug("[flow_report] loaded:", scriptSrc);
        }
      } catch (e) {}
    };
    script.onerror = (e) => {
      try {
        if (window && window.console && window.console.warn) {
          console.warn("[flow_report] failed to load:", scriptSrc, e);
        }
      } catch (err) {}
    };

    document.head.appendChild(script);
  } catch (e) {
    try { if (window && window.console) console.warn("[flow_report] inject error", e); } catch (err) {}
  }
})();

// App bootstrap (React.StrictMode kept)
const container = document.getElementById("root");
createRoot(container).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);