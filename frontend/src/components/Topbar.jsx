// frontend/src/components/Topbar.jsx
import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api, { getToken as apiGetToken, clearToken as apiClearToken } from "../services/api";
import { getStoredToken, clearStoredToken } from "../services/auth";
import { toast } from "../utils/toast";

export default function Topbar() {
  const nav = useNavigate();
  const [token, setToken] = useState(() => {
    try { return apiGetToken() || getStoredToken(); }
    catch { return getStoredToken(); }
  });
  const [username, setUsername] = useState(null);

  useEffect(() => {
    let mounted = true;

    async function loadUser() {
      const t = token || apiGetToken() || getStoredToken();
      setToken(t);

      if (!t || !mounted) return;

      try {
        const me = await (api.getUserInfo?.() ?? Promise.resolve(null));
        if (me?.username) setUsername(me.username);
      } catch {}

      if (t && t.split(".").length === 3) {
        try {
          const payload = JSON.parse(atob(t.split(".")[1]));
          if (payload?.username) setUsername(payload.username);
        } catch {}
      }
    }

    loadUser();

    const onLogin = (ev) => {
      const tok = ev?.detail?.token || apiGetToken() || getStoredToken();
      setToken(tok);
      if (ev?.detail?.username) setUsername(ev.detail.username);
    };

    const onLogout = () => {
      setToken(null);
      setUsername(null);
    };

    window.addEventListener("auth:login", onLogin);
    window.addEventListener("auth:logout", onLogout);

    return () => {
      mounted = false;
      window.removeEventListener("auth:login", onLogin);
      window.removeEventListener("auth:logout", onLogout);
    };
  }, [token]);

  function handleLogout() {
    try { api.logout(); } catch {}
    try { apiClearToken(); } catch {}
    try { clearStoredToken(); } catch {}
    toast("Logged out", "success", 650);
    window.dispatchEvent(new CustomEvent("auth:logout"));
    nav("/login", { replace: true });
  }

  return (
    <header className="topbar">
      <div className="topbar-inner">

        {/* Logo */}
        <div className="brand">
          <Link to="/" className="brand-link">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M12 2L20 7V17L12 22L4 17V7L12 2Z" fill="#0ea5e9" />
            </svg>
            <span className="brand-text">AI-ML CyberDefense</span>
          </Link>
        </div>

        {/* Right side */}
        <nav className="topnav">
          {!token ? (
            <>
              {/* Login in light red */}
              <Link to="/login" className="btn btn-cta-red">Login</Link>

              {/* Get Started in teal */}
              <Link to="/register" className="btn btn-cta">Get Started</Link>
            </>
          ) : (
            <>
              <span className="topnav-welcome">
                Welcome{username ? `, ${username}` : ""}
              </span>
              <button className="btn btn-danger" onClick={handleLogout}>
                Logout
              </button>
            </>
          )}
        </nav>

      </div>
    </header>
  );
}
