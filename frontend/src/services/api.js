// frontend/src/services/api.js


import {
  getStoredToken,
  setStoredToken,
  clearStoredToken,
  getStoredRefreshToken,
  setStoredRefreshToken,
  clearStoredRefreshToken,
} from "./auth";


const DEFAULT_TIMEOUT_MS = 25000;
const TOKEN_KEY = "auth_token_v1";
let _token = null;

function timeoutPromise(ms, promise) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      const err = new Error("Request timed out");
      err.name = "TimeoutError";
      reject(err);
    }, ms);
    promise
      .then((res) => {
        clearTimeout(timer);
        resolve(res);
      })
      .catch((err) => {
        clearTimeout(timer);
        reject(err);
      });
  });
}

async function normalizeResponse(res) {
  let text = "";
  try {
    text = await res.text();
  } catch (e) {
    text = "";
  }
  try {
    const body = text ? JSON.parse(text) : null;
    return { ok: res.ok, status: res.status, body };
  } catch (e) {
    return { ok: res.ok, status: res.status, body: text };
  }
}

function _fallbackGetRefreshToken() {
  try { return localStorage.getItem("refresh_token"); } catch (e) { return null; }
}
function _fallbackSetRefreshToken(t) {
  try { if (!t) localStorage.removeItem("refresh_token"); else localStorage.setItem("refresh_token", t); } catch (e) {}
}
function _fallbackClearRefreshToken() { try { localStorage.removeItem("refresh_token"); } catch (e) {} }

const _getStoredRefreshToken = typeof getStoredRefreshToken === "function" ? getStoredRefreshToken : _fallbackGetRefreshToken;
const _setStoredRefreshToken = typeof setStoredRefreshToken === "function" ? setStoredRefreshToken : _fallbackSetRefreshToken;
const _clearStoredRefreshToken = typeof clearStoredRefreshToken === "function" ? clearStoredRefreshToken : _fallbackClearRefreshToken;

const _envBase = (typeof process !== "undefined" && process.env && process.env.REACT_APP_API_BASE) ? process.env.REACT_APP_API_BASE : null;
export const API_BASE = (_envBase && _envBase.replace(/\/+$/, "")) || (typeof window !== "undefined" && window.__API_BASE) || "http://localhost:5000";

function makeUrl(path) {
  if (!path) return API_BASE;
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  if (!path.startsWith("/")) path = "/" + path;
  return API_BASE + path;
}

export function setToken(token, { persist = true } = {}) {
  try {
    _token = token || null;
    if (persist) {
      try {
        if (typeof setStoredToken === "function") setStoredToken(token);
        else {
          if (token) {
            localStorage.setItem(TOKEN_KEY, token);
            try { localStorage.setItem("jwt", token); } catch (e) {}
          } else {
            localStorage.removeItem(TOKEN_KEY);
            try { localStorage.removeItem("jwt"); } catch (e) {}
          }
        }
      } catch (e) { console.warn("setToken: persist failed", e); }
    }
    return true;
  } catch (e) {
    console.warn("setToken error:", e);
    return false;
  }
}

export function getToken() {
  if (_token) return _token;
  try {
    const s = (typeof getStoredToken === "function" ? getStoredToken() : localStorage.getItem(TOKEN_KEY) || localStorage.getItem("jwt"));
    _token = s || null;
    return _token;
  } catch (e) { return null; }
}

export function clearToken() {
  try {
    _token = null;
    if (typeof clearStoredToken === "function") clearStoredToken();
    else { localStorage.removeItem(TOKEN_KEY); try { localStorage.removeItem("jwt"); } catch (e) {} }
  } catch (e) { console.warn("clearToken failed:", e); _token = null; }
}

function buildHeaders(extraHeaders = {}) {
  const headers = Object.assign({}, extraHeaders || {});
  const token = _token || (typeof getStoredToken === "function" ? getStoredToken() : null);
  if (token) headers["Authorization"] = "Bearer " + token;
  return headers;
}

/* authFetch wrapper */
export async function authFetch(path, opts = {}, { timeout = DEFAULT_TIMEOUT_MS, retries = 0 } = {}) {
  const options = Object.assign({}, opts);
  options.headers = buildHeaders(options.headers || {});
  if (!options.credentials) options.credentials = "same-origin";

  if (options.body && typeof options.body === "object" && !(options.body instanceof FormData) && !(typeof options.body === "string")) {
    if (!options.headers["Content-Type"]) options.headers["Content-Type"] = "application/json";
    if (options.headers["Content-Type"].includes("application/json") && typeof options.body !== "string") options.body = JSON.stringify(options.body);
  }

  let attempt = 0;
  let triedRefresh = false;

  while (true) {
    try {
      const url = makeUrl(path);
      const res = await timeoutPromise(timeout, fetch(url, options));
      const parsed = await normalizeResponse(res);

      if (!res.ok) {
        if ((res.status === 401 || res.status === 403) && !triedRefresh) {
          const refreshToken = _getStoredRefreshToken();
          if (refreshToken) {
            triedRefresh = true;
            try {
              const refreshed = await refreshAuth(refreshToken);
              const newToken = (refreshed && (refreshed.access_token || refreshed.token || refreshed.auth_token || refreshed.jwt)) || (typeof getToken === "function" ? getToken() : null);
              if (newToken) {
                try { setToken(newToken, { persist: true }); } catch (e) {}
                options.headers = buildHeaders(options.headers || {});
                continue;
              }
            } catch (e) {
              try { clearToken(); } catch (err) {}
              try { _clearStoredRefreshToken(); } catch (err) {}
            }
          }
        }

        const message = parsed.body?.error || parsed.body?.message || `HTTP ${res.status}`;
        const err = new Error(message);
        err.status = res.status;
        err.body = parsed.body;
        throw err;
      }
      return parsed.body;
    } catch (err) {
      attempt++;
      const isNetwork = !err.status;
      if (attempt > retries || !isNetwork) throw err;
      await new Promise((r) => setTimeout(r, 200 * attempt));
    }
  }
}

/* normalizeModelResponse — canonical shape + fallbacks */
function normalizeModelResponse(res) {
  if (!res) return { botProb: null, percentBot: null, label: null, confidenceRaw: null, raw: res };

  if (Array.isArray(res) && res.length > 0) {
    const first = res[0];
    if (first && typeof first === "object") {
      const label = first.label || first.prediction || null;
      const candidate = first.bot_prob ?? first.prob ?? first.score ?? first.confidence ?? null;
      const num = (candidate != null && !Number.isNaN(Number(candidate))) ? Number(candidate) : null;
      if (num != null) {
        const lbl = label ? String(label).toLowerCase() : "";
        const botProb = (lbl === "human" && num > 0.5) ? (1 - num) : num;
        const clamped = Math.max(0, Math.min(1, botProb));
        return { botProb: clamped, percentBot: Math.round(clamped * 100), label, confidenceRaw: num, raw: res };
      }
    }
    if (res.length >= 2) {
      const pred = res[0];
      const sc = res[1];
      const num = (sc != null && !Number.isNaN(Number(sc))) ? Number(sc) : null;
      if (num != null) {
        const lbl = pred ? String(pred).toLowerCase() : "";
        let botProb = num;
        if (lbl === "human") botProb = 1 - num;
        const clamped = Math.max(0, Math.min(1, botProb));
        return { botProb: clamped, percentBot: Math.round(clamped * 100), label: pred, confidenceRaw: num, raw: res };
      }
    }
  }

  if (typeof res === "number" && !Number.isNaN(res)) {
    let n = Number(res);
    if (n > 1) n = n / 100.0;
    const clamped = Math.max(0, Math.min(1, n));
    return { botProb: clamped, percentBot: Math.round(clamped * 100), label: clamped >= 0.5 ? "bot" : "human", confidenceRaw: n, raw: res };
  }

  if (typeof res === "object") {
    const obj = res;
    const maybeBot = obj.bot_prob ?? obj.botProb ?? obj.bot ?? obj.botProbability ?? obj.prob_bot;
    const maybeHuman = obj.human_prob ?? obj.humanProb ?? obj.human ?? obj.humanProbability ?? obj.prob_human;
    const maybeConf = obj.confidence ?? obj.score ?? obj.prob ?? obj.probability ?? obj.value;

    if (maybeBot != null && !Number.isNaN(Number(maybeBot))) {
      const n = Number(maybeBot);
      const clamped = Math.max(0, Math.min(1, n));
      return { botProb: clamped, percentBot: Math.round(clamped * 100), label: obj.label || obj.prediction || obj.result || null, confidenceRaw: n, raw: res };
    }
    if (maybeHuman != null && !Number.isNaN(Number(maybeHuman))) {
      const n = Number(maybeHuman);
      const bot = 1 - n;
      const clamped = Math.max(0, Math.min(1, bot));
      return { botProb: clamped, percentBot: Math.round(clamped * 100), label: obj.label || obj.prediction || obj.result || null, confidenceRaw: n, raw: res };
    }
    if (maybeConf != null && !Number.isNaN(Number(maybeConf))) {
      let n = Number(maybeConf);
      if (n > 1) n = n / 100.0;
      const label = (obj.label || obj.prediction || obj.result || "").toString().toLowerCase();
      let botProb = n;
      if (label === "human" && n > 0.5) botProb = 1 - n;
      const clamped = Math.max(0, Math.min(1, botProb));
      return { botProb: clamped, percentBot: Math.round(clamped * 100), label: obj.label || obj.prediction || obj.result || null, confidenceRaw: n, raw: res };
    }

    for (const k of ["prob", "score", "confidence", "pred", "value"]) {
      if (obj[k] != null && !Number.isNaN(Number(obj[k]))) {
        let n = Number(obj[k]);
        if (n > 1) n = n / 100.0;
        const clamped = Math.max(0, Math.min(1, n));
        return { botProb: clamped, percentBot: Math.round(clamped * 100), label: obj.label || null, confidenceRaw: n, raw: res };
      }
    }
  }

  return { botProb: null, percentBot: null, label: null, confidenceRaw: null, raw: res };
}

export async function postJSON(url, body = {}) {
  try {
    const fullUrl = makeUrl(url);
    const res = await timeoutPromise(DEFAULT_TIMEOUT_MS, fetch(fullUrl, {
      method: "POST",
      headers: buildHeaders({ "Content-Type": "application/json", Accept: "application/json" }),
      credentials: "same-origin",
      body: JSON.stringify(body)
    }));
    const data = await (res.json().catch(async () => { const t = await res.text().catch(()=>null); return t; }));
    return { status: res.status, ok: res.ok, data };
  } catch (err) {
    return { status: 0, ok: false, data: null, error: err.message || String(err) };
  }
}

export async function login(username, password) {
  if (!username || !password) throw new Error("username and password required");
  const body = await authFetch("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
    headers: { "Content-Type": "application/json" },
  }, { retries: 0, timeout: 20000 });

  const token = body?.token || body?.access_token || body?.auth_token || body?.accessToken || body?.jwt;
  if (token) {
    try { if (typeof setStoredToken === "function") setStoredToken(token); } catch (e) {}
    try { setToken(token, { persist: true }); } catch (e) {}
  }
  const refresh = body?.refresh_token || body?.refreshToken;
  if (refresh) _setStoredRefreshToken(refresh);
  return Object.assign({}, body, { token });
}

export async function register(username, password, email = null) {
  if (!username || !password) throw new Error("username and password required");
  const body = await authFetch("/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password, email }),
    headers: { "Content-Type": "application/json" },
  }, { retries: 0, timeout: 20000 });
  const token = body?.token || body?.access_token || body?.auth_token || body?.jwt;
  if (token) { try { if (typeof setStoredToken === "function") setStoredToken(token); } catch (e) {} try { setToken(token, { persist: true }); } catch(e){} }
  const refresh = body?.refresh_token || body?.refreshToken;
  if (refresh) _setStoredRefreshToken(refresh);
  return body;
}

export async function refreshAuth(refreshToken = null) {
  const rt = refreshToken || _getStoredRefreshToken();
  if (!rt) throw new Error("no_refresh_token");
  const res = await timeoutPromise(DEFAULT_TIMEOUT_MS, fetch(makeUrl("/auth/refresh"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ refresh_token: rt })
  }));
  const parsed = await normalizeResponse(res);
  if (!res.ok) {
    const err = new Error(parsed.body?.error || parsed.body?.message || `HTTP ${res.status}`);
    err.status = res.status; err.body = parsed.body; throw err;
  }
  const access = parsed.body?.access_token || parsed.body?.token || parsed.body?.auth_token || parsed.body?.jwt;
  if (access) { try { if (typeof setStoredToken === "function") setStoredToken(access); } catch(e){} try { setToken(access, { persist: true }); } catch(e){} }
  const newRefresh = parsed.body?.refresh_token || parsed.body?.refreshToken;
  if (newRefresh) { try { _setStoredRefreshToken(newRefresh); } catch(e){} }
  return parsed.body;
}

export async function logout(refreshToken = null) {
  const rt = refreshToken || _getStoredRefreshToken();
  try {
    if (rt) {
      await timeoutPromise(10000, fetch(makeUrl("/auth/logout"), { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ refresh_token: rt }) })).catch(()=>{});
    } else {
      await timeoutPromise(8000, fetch(makeUrl("/auth/logout"), { method: "POST", credentials: "same-origin" })).catch(()=>{});
    }
  } catch (e) {
  } finally {
    try { if (typeof clearStoredToken === "function") clearStoredToken(); } catch (e) {}
    try { _clearStoredRefreshToken(); } catch (e) {}
    _token = null;
    try { window.dispatchEvent(new CustomEvent("auth:logout")); } catch (e) {}
  }
}

export function clearTokensLocal() {
  try { if (typeof clearStoredToken === "function") clearStoredToken(); } catch (e) {}
  try { _clearStoredRefreshToken(); } catch (e) {}
  _token = null;
}

export async function fetchAlerts() {
  const candidates = [ "/api/alerts", "/alerts" ];
  let lastErr = null;
  for (const url of candidates) {
    try {
      const body = await authFetch(url, { method: "GET" }, { retries: 0, timeout: 8000 });
      if (!body) return [];
      if (Array.isArray(body)) return body;
      return body?.alerts || [];
    } catch (err) {
      lastErr = err;
      if (err && err.status === 404) continue;
      continue;
    }
  }
  console.warn("fetchAlerts: all endpoints failed; returning []. last error:", lastErr);
  return [];
}

export async function fetchHealth() { return await authFetch("/health", { method: "GET" }, { retries: 1 }); }
export async function fetchModelStatus() { return await authFetch("/admin/model_status", { method: "GET" }, { retries: 1 }); }

export async function collectMouse(payload = { session_id: null, events: [], meta: {}, predict: false }) {
  const res = await authFetch("/api/collect_mouse", {
    method: "POST",
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" },
  }, { retries: 0 });

  try {
    if (res && res.prediction) {
      // normalize raw prediction
      const norm = normalizeModelResponse(res.prediction);
      res.prediction_normalized = norm;

      const compat = {
        label: norm.label ?? (res.prediction.label || res.prediction.prediction || null),
        confidence: norm.confidenceRaw ?? (res.prediction.confidence ?? res.prediction.score ?? res.prediction.prob ?? null),
        bot_prob: (norm.botProb != null ? norm.botProb : (res.prediction.bot_prob ?? res.prediction.botProb ?? null)),
        human_prob: (norm.botProb != null ? 1 - norm.botProb : (res.prediction.human_prob ?? null)),
        score: norm.confidenceRaw ?? (res.prediction.score ?? null),
        raw: res.prediction
      };
      res.prediction_compat = compat;
    }
  } catch (e) {
    console.warn("collectMouse normalization failed", e);
  }
  return res;
}

export async function sendMouseBatch(payload = { session_id: null, events: [], meta: {}, predict: false }) {
  return await collectMouse(payload);
}

export async function predictMouse(events = []) {
  if (!events || !Array.isArray(events) || events.length === 0) {
    throw new Error("events required");
  }

  const body = await authFetch("/api/predict_mouse", {
    method: "POST",
    body: JSON.stringify({ events }),
    headers: { "Content-Type": "application/json" },
  }, { retries: 0, timeout: 15000 });

  function toNumber(v) {
    if (v == null) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  let bot = toNumber(body?.bot_prob ?? body?.botProb ?? body?.bot ?? body?.confidence ?? body?.prob ?? body?.score);
  let human = toNumber(body?.human_prob ?? body?.humanProb ?? body?.human);

  if (bot == null && human != null) bot = 1 - human;
  if (human == null && bot != null) human = 1 - bot;

  if (bot == null) {
    const label = (body?.label || body?.prediction || "").toString().toLowerCase();
    const score = toNumber(body?.score ?? body?.confidence ?? body?.prob);
    if (score != null) {
      if (label === "human" || label === "benign" || label === "0") bot = 1 - score;
      else if (label === "bot" || label === "attack" || label === "1") bot = score;
      else bot = score; // assume score is bot_prob
    } else {
      try {
        const per = body?.details?.per_window;
        if (Array.isArray(per) && per.length) {
          const vals = per.flatMap(w => {
            if (!w) return [];
            if (w.avg != null) return [Number(w.avg)];
            const arr = [];
            if (w.rf != null) arr.push(Number(w.rf));
            if (w.lstm != null) arr.push(Number(w.lstm));
            return arr;
          }).filter(Number.isFinite);
          if (vals.length) bot = vals.reduce((a,b) => a+b) / vals.length;
        }
      } catch (e) {}
    }
  }

  if (bot == null) bot = 0.05;
  bot = Math.max(0, Math.min(1, Number(bot)));
  if (human == null) human = 1 - bot;

  const canonical = Object.assign({
    bot_prob: bot,
    human_prob: human,
    confidence: bot,
    confidence_is: "bot_prob",
    _server_latency_ms: body?._server_latency_ms ?? null,
  }, body || {});

  return canonical;
}

export async function predictFlow(features = [], meta = {}) {
  if (!features || !Array.isArray(features) || features.length === 0) throw new Error("features required");
  return await authFetch("/predict_flow", {
    method: "POST",
    body: JSON.stringify({ features, meta }),
    headers: { "Content-Type": "application/json" },
  }, { retries: 0 });
}

export async function collectFlowEvent(payload = { features: [], meta: {} }) {
  return await authFetch("/collect_flow_event", {
    method: "POST",
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" }
  }, { retries: 0 });
}

export async function collectAndCheck(payload = { features: [], meta: {}, persist: false }) {
  try {
    return await authFetch("/collect_and_check", {
      method: "POST",
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json" }
    }, { retries: 0 });
  } catch (e) {
    return await predictFlow(payload.features || [], payload.meta || {});
  }
}

export async function predictCombined({ flow = null, mouse = null, weights = { flow: 0.5, mouse: 0.5 }, meta = {} } = {}) {
  if (!flow && !mouse) throw new Error("Either flow or mouse input required");
  return await authFetch("/api/predict_combined", {
    method: "POST",
    body: JSON.stringify({ flow, mouse, weights, meta }),
    headers: { "Content-Type": "application/json" },
  }, { retries: 0 });
}

export async function uploadFile(path, files = {}, fields = {}) {
  const form = new FormData();
  Object.keys(files).forEach((k) => {
    const v = files[k];
    if (v) form.append(k, v);
  });
  Object.keys(fields || {}).forEach((k) => {
    form.append(k, fields[k]);
  });

  const token = _token || (typeof getStoredToken === "function" ? getStoredToken() : null);
  const headers = {};
  if (token) headers["Authorization"] = "Bearer " + token;

  const res = await timeoutPromise(DEFAULT_TIMEOUT_MS, fetch(makeUrl(path), { method: "POST", body: form, headers, credentials: "same-origin" }));
  const parsed = await normalizeResponse(res);
  if (!res.ok) {
    const err = new Error(parsed.body?.error || `Upload failed: ${res.status}`);
    err.status = res.status;
    err.body = parsed.body;
    throw err;
  }
  return parsed.body;
}

export async function getAlertsPage(page = 1, perPage = 50) {
  const q = new URLSearchParams({ page: String(page), per_page: String(perPage) });
  return await authFetch(`/api/alerts?${q.toString()}`, { method: "GET" }, { retries: 1 });
}

export async function getUserInfo() {
  return await authFetch("/api/whoami", { method: "GET" }, { retries: 0 }).catch(() => null);
}

export default {
  authFetch,
  login,
  register,
  setToken,
  getToken,
  clearToken,
  clearTokensLocal,
  refreshAuth,
  logout,
  fetchAlerts,
  fetchHealth,
  fetchModelStatus,
  collectMouse,
  sendMouseBatch,
  predictMouse,
  predictFlow,
  collectFlowEvent,
  collectAndCheck,
  predictCombined,
  uploadFile,
  getAlertsPage,
  getUserInfo,
  postJSON,
  API_BASE
};