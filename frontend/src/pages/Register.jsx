// frontend/src/pages/Register.jsx
import React, { useState, useMemo, useEffect } from "react";
import { register } from "../services/api";
import { useNavigate, Link } from "react-router-dom";
import { toast } from "../utils/toast";
import Topbar from "../components/Topbar";
import useMouseDynamics from "../hooks/useMouseDynamics";
import { detectAutomation } from "../utils/automation";

/**
 Password policy: min length 8, at least one letter, at least one digit, at least one special char (from allowed set), only allowed chars (letters, digits, allowed special chars)
 */
const ALLOWED_SPECIALS = `!@#$%^&*()_+\\-=[\\]{};':"\\\\|,.<>/?\`~`;
const allowedCharsRegex = new RegExp(`^[A-Za-z0-9${ALLOWED_SPECIALS}]+$`);
const hasLetter = /[A-Za-z]/;
const hasDigit = /[0-9]/;
const hasSpecial = new RegExp(`[${ALLOWED_SPECIALS}]`);

function getStrengthPercent(pw) {
  if (!pw) return 0;
  let score = 0;
  if (pw.length >= 8) score += 30;
  if (pw.length >= 12) score += 10; 
  if (hasLetter.test(pw)) score += 20;
  if (hasDigit.test(pw)) score += 20;
  if (hasSpecial.test(pw)) score += 20;
  return Math.min(100, score);
}

function validatePassword(pw) {
  if (!pw || typeof pw !== "string") return { ok: false, reason: "Password required" };
  if (pw.length < 8) return { ok: false, reason: "Password must be at least 8 characters long" };
  if (!allowedCharsRegex.test(pw)) return { ok: false, reason: "Password contains invalid characters (no spaces allowed)" };
  if (!hasLetter.test(pw)) return { ok: false, reason: "Password must include at least one letter (a–z/A–Z)" };
  if (!hasDigit.test(pw)) return { ok: false, reason: "Password must include at least one number (0–9)" };
  if (!hasSpecial.test(pw)) return { ok: false, reason: "Password must include at least one special character (e.g. !@#$%)" };
  return { ok: true };
}

export default function Register() {
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [isAuto, setIsAuto] = useState(false);

  const { blocked, unblock } = useMouseDynamics({ intervalMs: 3000, batchLimit: 800, enableSend: true });

  useEffect(() => {
    try {
      setIsAuto(detectAutomation());
    } catch (e) {
      setIsAuto(false);
    }
  }, []);

  useEffect(() => {
    if (blocked) {
      setIsAuto(true);
      toast("Automation detected by server — registration blocked", "error", 3500);
    }
  }, [blocked]);

  const strength = useMemo(() => getStrengthPercent(password), [password]);
  const pwValidation = useMemo(() => validatePassword(password), [password]);

  async function submit(e) {
    e.preventDefault();

    if (isAuto) {
      toast("Automation detected — registration blocked", "error");
      return;
    }
    if (blocked) {
      toast("Session flagged as automated by server — registration temporarily blocked", "error");
      return;
    }

    if (!username) {
      toast("Please enter a username", "error");
      return;
    }

    const v = validatePassword(password);
    if (!v.ok) {
      toast(v.reason, "error");
      return;
    }

    setLoading(true);
    try {
      await register(username, password, email);
      toast("Account created — please login", "success", 2000);
      setTimeout(() => nav("/login"), 700);
    } catch (err) {
      console.error(err);
      const message =
        (err && err.body && (err.body.error || err.body.message)) ||
        err.message ||
        "Register failed";
      toast(message, "error", 3200);
    } finally {
      setLoading(false);
    }
  }

  // Handler for "I'm human — request review" button
  function handleRequestReview() {
    try {
      unblock();
      toast("Human review requested — please complete any challenges shown.", "info", 3000);
    } catch (e) {
      console.error("unblock failed", e);
      toast("Request failed — please try again", "error");
    }
  }

  return (
    <div className="page-root">
      <Topbar />
      <div className="auth-wrap">
        <div className="centered-card">
          <div className="logo-badge-large" aria-hidden>
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path d="M12 2L20 7V17L12 22L4 17V7L12 2Z" fill="#0ea5e9" />
            </svg>
          </div>

          <h2 className="auth-title">Create account</h2>
          <p className="auth-sub">Secure your dashboard</p>

          <form className="auth-form" onSubmit={submit} autoComplete="off">
            <label className="form-label" htmlFor="register-username">Username</label>
            <div className="input-row">
              <input
                id="register-username"
                name = "username"
                className="auth-input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Pick a username"
                autoComplete="username"
                spellCheck="false"
              />
            </div>

            <label className="form-label" htmlFor="register-email">Email</label>
            <div className="input-row">
              <input
                id="register-email"
                name="email"
                className="auth-input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Enter email (optional)"
                autoComplete="email"
              />
            </div>

            <label className="form-label" htmlFor="register-password">Password</label>
            <div className="input-row">
              <input
                id="register-password"
                name="password"
                className="auth-input"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Choose a strong password"
                autoComplete="new-password"
              />
              <button
                type="button"
                onClick={() => setShowPassword((s) => !s)}
                className="eye-btn"
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
                    <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" stroke="#b7dbe6" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                    <circle cx="12" cy="12" r="3.2" fill="#b7dbe6" />
                  </svg>
                ) : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
                    <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" stroke="#9fb7c3" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                    <circle cx="12" cy="12" r="2.2" fill="#9fb7c3" />
                  </svg>
                )}
              </button>
            </div>

            {/* Password strength bar and inline validation */}
            <div style={{ marginTop: 6 }}>
              <div className="password-strength" aria-hidden>
                <i style={{ width: `${strength}%` }} />
              </div>
              {!pwValidation.ok && password.length > 0 && (
                <div style={{ color: "#fca5a5", marginTop: 8, fontSize: 13 }}>{pwValidation.reason}</div>
              )}
            </div>

            <button
              type="submit"
              className="btn primary auth-submit"
              disabled={loading}
              aria-busy={loading}
            >
              {loading ? "Creating..." : "Register"}
            </button>
          </form>

          <div className="auth-foot" style={{ marginTop: 14 }}>
            <span>Already have an account? </span>
            <Link to="/login" className="link-primary">
              Login
            </Link>
          </div>

          {/* Small human-review control (non-intrusive) */}
          <div style={{ marginTop: 8, display: "flex", gap: 12, alignItems: "center" }}>
            <button
              type="button"
              onClick={handleRequestReview}
              className="btn outline"
              style={{ padding: "6px 10px", fontSize: 13 }}
            >
              I'm human — request review
            </button>

            {/* show a small status label if server blocked this session */}
            {blocked ? (
              <span style={{ color: "#f87171", fontSize: 13 }}>Server flagged this session as automated</span>
            ) : isAuto ? (
              <span style={{ color: "#f59e0b", fontSize: 13 }}>Local automation heuristic triggered</span>
            ) : (
              <span style={{ color: "var(--muted)", fontSize: 13 }}>Session protected — mouse dynamics collected</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}