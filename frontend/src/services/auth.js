// frontend/src/services/auth.js
const AUTH_KEY = "auth_token_v1";

export function getStoredToken() {
  try {
    return localStorage.getItem(AUTH_KEY) || localStorage.getItem("jwt") || null;
  } catch (e) {
    console.warn("getStoredToken failed", e);
    return null;
  }
}

export function setStoredToken(token) {
  try {
    if (!token) {
      localStorage.removeItem(AUTH_KEY);
      try { localStorage.removeItem("jwt"); } catch (e) {}
      return;
    }
    localStorage.setItem(AUTH_KEY, token);
    try { localStorage.setItem("jwt", token); } catch (e) {}
  } catch (e) {
    console.warn("setStoredToken failed", e);
  }
}

export function clearStoredToken() {
  try {
    localStorage.removeItem(AUTH_KEY);
    try { localStorage.removeItem("jwt"); } catch (e) {}
  } catch (e) {
    console.warn("clearStoredToken failed", e);
  }
}

export function getStoredRefreshToken() {
  try { return localStorage.getItem("refresh_token") || null; } catch (e) { return null; }
}
export function setStoredRefreshToken(token) {
  try { if (!token) localStorage.removeItem("refresh_token"); else localStorage.setItem("refresh_token", token); } catch (e) {}
}
export function clearStoredRefreshToken() {
  try { localStorage.removeItem("refresh_token"); } catch (e) {}
}

export default {
  getStoredToken,
  setStoredToken,
  clearStoredToken,
  getStoredRefreshToken,
  setStoredRefreshToken,
  clearStoredRefreshToken,
  AUTH_KEY
};
