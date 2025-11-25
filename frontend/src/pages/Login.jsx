// frontend/src/pages/Login.jsx
import React, { useState, useEffect, useRef } from "react";
import api, { login as apiLogin, setToken as apiSetToken } from "../services/api";
import { setStoredToken } from "../services/auth";
import { useNavigate, Link } from "react-router-dom";
import { detectAutomation } from "../utils/automation";
import { toast } from "../utils/toast";
import Topbar from "../components/Topbar";
import useMouseDynamics from "../hooks/useMouseDynamics";

export default function Login() {
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [isAuto, setIsAuto] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const { blocked, unblock } = useMouseDynamics({
    intervalMs: 3000,
    batchLimit: 800,
    enableSend: true,
  });

  useEffect(() => {
    try {
      setIsAuto(Boolean(detectAutomation && detectAutomation()));
    } catch (e) {
      setIsAuto(false);
    }
  }, []);

  useEffect(() => {
    if (blocked) {
      setIsAuto(true);
      toast("Automation detected by server — interactions blocked", "error", 3500);
    }
  }, [blocked]);

  const didRedirectRef = useRef(false);

  function persistAndSignalLogin(token, usernameForSignal = null) {
    try {
      try {
        if (typeof setStoredToken === "function") setStoredToken(token);
        else {
          if (token) {
            localStorage.setItem("auth_token_v1", token);
            try { localStorage.setItem("jwt", token); } catch (e) {}
          } else {
            localStorage.removeItem("auth_token_v1");
            try { localStorage.removeItem("jwt"); } catch (e) {}
          }
        }
      } catch (e) {
        console.warn("persistAndSignalLogin: setStoredToken failed", e);
      }

      try {
        apiSetToken(token, { persist: true }); 
      } catch (e) {
        console.warn("persistAndSignalLogin: apiSetToken failed", e);
      }

      try {
        window.dispatchEvent(new CustomEvent("auth:login", { detail: { token, username: usernameForSignal || username } }));
      } catch (e) {
        console.warn("auth:login dispatch failed", e);
      }

      try {
        if (typeof window.__SET_AUTH_STATE === "function") {
          window.__SET_AUTH_STATE({ token, user: { username: usernameForSignal || username } });
        }
      } catch (e) {
      }

      try {
        if (window.__APP_STORE__ && typeof window.__APP_STORE__.dispatch === "function") {
          window.__APP_STORE__.dispatch({ type: "AUTH_LOGIN_SUCCESS", payload: { token, user: { username: usernameForSignal || username } } });
        }
      } catch (e) {}
    } catch (e) {
      console.warn("persistAndSignalLogin error:", e);
    }
  }

  function safeNavigateToDashboard() {
    if (didRedirectRef.current) return;
    didRedirectRef.current = true;

    try {
      nav("/dashboard", { replace: true });
    } catch (e) {
      console.warn("SPA navigate threw:", e);
    }

    setTimeout(() => {
      try {
        const path = window.location.pathname + (window.location.search || "");
        if (!path.startsWith("/dashboard")) {
          window.location.replace("/dashboard");
        }
      } catch (err) {
        console.warn("safeNavigateToDashboard fallback error:", err);
        try {
          window.location.replace("/dashboard");
        } catch (_) {}
      }
    }, 180);
  }

  async function submit(e) {
    e.preventDefault();

    if (isAuto) {
      toast("Automation detected — login blocked", "error");
      return;
    }
    if (blocked) {
      toast("Session flagged as automated by server — login temporarily blocked", "error");
      return;
    }
    if (!username || !password) {
      toast("Please enter username and password", "error");
      return;
    }

    setLoading(true);
    try {
      const data = await apiLogin(username, password);

      const token = (data && (data.token || data.access_token || data.auth_token || data.jwt || data.accessToken)) || null;

      if (!token) {
        console.warn("Login succeeded but no token returned:", data);
        toast("Login succeeded but server returned no token. Trying to open dashboard...", "warning", 2500);
        safeNavigateToDashboard();
        return;
      }

      persistAndSignalLogin(token, username);

      toast("Login successful — redirecting to dashboard", "success", 1000);

      setTimeout(() => {
        safeNavigateToDashboard();
      }, 220);
    } catch (err) {
      console.error("login error:", err);
      const message =
        (err && err.body && (err.body.error || err.body.message)) ||
        err.message ||
        (err && err.error) ||
        "Login failed";
      toast(message, "error", 3200);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    return () => {
      try {
        if (typeof unblock === "function") unblock();
      } catch (e) {}
    };
  }, [unblock]);

  return (
    <div className="page-root">
      <Topbar />
      <div className="auth-wrap">
        <div className="auth-card centered-card">
          <div className="logo-badge-large" aria-hidden>
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path d="M12 2L20 7V17L12 22L4 17V7L12 2Z" fill="#0ea5e9" />
            </svg>
          </div>

          <h2 className="auth-title">AI-ML CyberDefense</h2>
          <p className="auth-sub">Login to access your security dashboard</p>

          <form className="auth-form" onSubmit={submit} autoComplete="off">
            <label className="form-label" htmlFor="login-username">Username</label>
            <div className="input-row">
              <input
                id="login-username"
                name="username"
                className="auth-input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter your username"
                autoComplete="username"
                spellCheck="false"
                required
              />
            </div>

            <label className="form-label" htmlFor="login-password" style={{ marginTop: 8 }}>Password</label>
            <div className="input-row">
              <input
                id="login-password"
                name="password"
                className="auth-input"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                autoComplete="current-password"
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword((s) => !s)}
                className="eye-btn"
                aria-label={showPassword ? "Hide password" : "Show password"}
                tabIndex={0}
              >
                {showPassword ? "👁️" : "👁️‍🗨️"}
              </button>
            </div>

            <button type="submit" className="btn primary auth-submit" disabled={loading} aria-busy={loading}>
              {loading ? "Logging in..." : "Login"}
            </button>
          </form>

          <div className="auth-foot">
            <span>Don't have an account? </span>
            <Link to="/register" className="link-primary">Register</Link>
          </div>

          <div className="auth-note" style={{ marginTop: 12 }}>
            {blocked ? (
              <span style={{ color: "#f87171" }}>
                Server flagged this session as automated — interactions may be limited
              </span>
            ) : isAuto ? (
              <span style={{ color: "#f87171" }}>Automation detected — some features are blocked</span>
            ) : (
              <span style={{ color: "var(--muted)" }}>
                Your session is protected. We collect mouse dynamics for bot detection.
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}