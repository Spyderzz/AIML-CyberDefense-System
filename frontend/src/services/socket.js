// frontend/src/services/socket.js

import { io } from "socket.io-client";
import { getStoredToken } from "./auth";

export function connectSocket(onAlert, onMousePrediction) {
  const token = getStoredToken();

  const socket = io("/", {
    transports: ["websocket"],
    auth: { token: token ? `Bearer ${token}` : null },
    autoConnect: true,
    reconnectionAttempts: 3,
  });

  socket.on("connect", () => {
    console.info("Socket connected:", socket.id);
  });

  socket.on("disconnect", (reason) => {
    console.info("Socket disconnected:", reason);
  });

  socket.on("connect_error", (err) => {
    console.warn("Socket connect_error:", err && err.message ? err.message : err);
  });

  socket.on("new_alert", (payload) => {
    try {
      if (typeof onAlert === "function") onAlert(payload);
    } catch (e) {
      console.warn("onAlert handler error:", e);
    }
  });

  socket.on("mouse_prediction", (payload) => {
    try {
      if (typeof onMousePrediction === "function") onMousePrediction(payload);
    } catch (e) {
      console.warn("onMousePrediction handler error:", e);
    }
  });

  socket.on("message", (m) => {
    console.debug("socket message:", m);
  });

  return socket;
}