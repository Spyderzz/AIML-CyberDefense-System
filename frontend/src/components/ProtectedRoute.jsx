// frontend/src/components/ProtectedRoute.jsx
import React from "react";
import { Navigate, Outlet } from "react-router-dom";
import api, { getToken as apiGetToken } from "../services/api";

function readStorageToken() {
  try {
    return (
      localStorage.getItem("auth_token_v1") ||
      localStorage.getItem("jwt") ||
      null
    );
  } catch (e) {
    return null;
  }
}

export default function ProtectedRoute({ children }) {
  let token = null;
  try {
    if (typeof apiGetToken === "function") {
      token = apiGetToken();
    } else if (api && typeof api.getToken === "function") {
      token = api.getToken();
    }
  } catch (e) {
    token = null;
  }

  if (!token) token = readStorageToken();
  const isAuthenticated = Boolean(token);
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  if (children) return <>{children}</>;
  return <Outlet />;
}