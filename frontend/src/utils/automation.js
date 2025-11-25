// frontend/src/utils/automation.js

let postHandler;
try {
  import("../services/api").then(mod => {
    if (mod && typeof mod.postJSON === "function") postHandler = mod.postJSON;
  }).catch(()=>{ /* ignore; fallback below */ });
} catch (e) {
}

async function _postJSON(url, body) {
  try {
    const res = await fetch(url, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(()=>({}));
    return { status: res.status, ok: res.ok, data };
  } catch (e) {
    console.warn("postJSON fallback failed", e);
    return { status: 0, ok: false, data: null, error: e.message || e };
  }
}

postHandler = postHandler || _postJSON;

const BATCH_INTERVAL_MS = 3000;   // send every 3s
const MAX_BUFFER = 5000;          // max events kept in memory before trimming
const SEND_MIN = 6;               // minimum events to send at once
const OVERLAY_ID = "__bot_block_overlay_v1";
const ENDPOINT = "/api/collect_mouse";

// Prevent duplicate initialization across hook + global script
if (typeof window !== "undefined" && window.__mouse_collector_registered) {
  console.info("Mouse collector already registered — skipping duplicate initialization.");
} else {
  if (typeof window !== "undefined") window.__mouse_collector_registered = true;

  if (typeof window !== "undefined") {
    window.__mouse_buffer = window.__mouse_buffer || [];
    window.__mouse_session = window.__mouse_session || ("s_" + Math.floor(Date.now() / 1000) + "_" + Math.random().toString(36).slice(2,8));
    window.__mouse_last_sent = window.__mouse_last_sent || null;
    window.__mouse_blocked = window.__mouse_blocked || false;
  }

  function pushToBuffer(evt) {
    try {
      window.__mouse_buffer.push(evt);
      if (window.__mouse_buffer.length > MAX_BUFFER) {
        window.__mouse_buffer.splice(0, window.__mouse_buffer.length - MAX_BUFFER);
      }
    } catch (e) { /* ignore */ }
  }
  window.__mouse_push = window.__mouse_push || pushToBuffer;

  (function attachListeners() {
    if (window.__mouse_listeners_attached) return;
    window.__mouse_listeners_attached = true;

    document.addEventListener("mousemove", ev => {
      window.__mouse_push({ x: ev.clientX, y: ev.clientY, t: Date.now(), type: "move" });
    }, { passive: true });

    document.addEventListener("mousedown", ev => {
      window.__mouse_push({ x: ev.clientX, y: ev.clientY, t: Date.now(), type: "mousedown", button: ev.button });
    }, { passive: true });

    document.addEventListener("mouseup", ev => {
      window.__mouse_push({ x: ev.clientX, y: ev.clientY, t: Date.now(), type: "mouseup", button: ev.button });
    }, { passive: true });

    document.addEventListener("click", ev => {
      window.__mouse_push({ x: ev.clientX, y: ev.clientY, t: Date.now(), type: "click" });
    }, { passive: true });

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") {
        trySend(true).catch(()=>{});
      }
    });
  })();

  function compute_basic_features(events) {
    if (!events || events.length < 2) return {};
    let last = events[0];
    const speeds = [];
    const dts = [];
    const angles = [];
    let clicks = 0;
    for (let i=1;i<events.length;i++){
      const e = events[i];
      if (!e || typeof e.x !== "number") continue;
      const dx = e.x - last.x;
      const dy = e.y - last.y;
      const dt = Math.max(1, (e.t - last.t) || 1) / 1000; // seconds
      const s = Math.sqrt(dx*dx + dy*dy) / dt;
      speeds.push(s);
      dts.push(dt);
      angles.push(Math.atan2(dy, dx));
      if (e.type === "click" || e.type === "mousedown") clicks++;
      last = e;
    }
    const average = arr => arr.length ? arr.reduce((a,b)=>a+b,0)/arr.length : 0;
    const std = arr => {
      if (!arr.length) return 0;
      const m = average(arr);
      return Math.sqrt(arr.reduce((s,x)=>s+(x-m)*(x-m),0)/arr.length);
    };
    const diffs = [];
    for (let i=1;i<angles.length;i++){
      let da = angles[i] - angles[i-1];
      while (da <= -Math.PI) da += 2*Math.PI;
      while (da > Math.PI) da -= 2*Math.PI;
      diffs.push(Math.abs(da));
    }
    return {
      avg_speed: average(speeds),
      max_speed: speeds.length ? Math.max(...speeds) : 0,
      std_speed: std(speeds),
      avg_dt: average(dts),
      std_dt: std(dts),
      curvature: std(diffs),
      clicks,
      count: events.length
    };
  }

  function showBlockOverlay(reasonText = "Automation/bot movement detected. Page blocked.") {
    if (window.__mouse_blocked) return;
    window.__mouse_blocked = true;

    const overlay = document.createElement("div");
    overlay.id = OVERLAY_ID;
    overlay.style.position = "fixed";
    overlay.style.left = "0";
    overlay.style.top = "0";
    overlay.style.width = "100%";
    overlay.style.height = "100%";
    overlay.style.zIndex = 999999999;
    overlay.style.background = "linear-gradient(180deg, rgba(2,6,12,0.85), rgba(2,6,12,0.95))";
    overlay.style.display = "flex";
    overlay.style.justifyContent = "center";
    overlay.style.alignItems = "center";
    overlay.style.color = "#fff";
    overlay.style.fontFamily = "Inter, system-ui, Arial";
    overlay.style.flexDirection = "column";
    overlay.innerHTML = `
      <div style="max-width:820px;padding:28px;border-radius:10px;text-align:center;background: rgba(0,0,0,0.25);box-shadow:0 12px 40px rgba(0,0,0,0.6);">
        <h2 style="margin:0 0 10px;font-size:22px">Automation detected</h2>
        <p style="margin:0 0 18px;opacity:0.9">${reasonText}</p>
        <button id="__mouse_unblock_try" style="padding:10px 18px;border-radius:8px;border:none;background:#06b6d4;color:#002b33;cursor:pointer;font-weight:700">I am human — request review</button>
        <div style="margin-top:12px;font-size:12px;opacity:0.85">If you believe this was a mistake, press the button to request review (this sends a verification request to the server).</div>
      </div>
    `;
    document.body.appendChild(overlay);
    const btn = document.getElementById("__mouse_unblock_try");
    btn?.addEventListener("click", async ()=>{
      try {
        await postHandler(ENDPOINT, { session_id: window.__mouse_session, meta: { action: "recheck" } });
        const el = document.getElementById(OVERLAY_ID);
        if (el) el.remove();
        window.__mouse_blocked = false;
      } catch(e) {
        console.warn("recheck failed", e);
      }
    });
  }

  let sending = false;
  async function trySend(force=false) {
    if (sending) return;
    if (window.__mouse_blocked) return;
    if (!force && (!window.__mouse_buffer || window.__mouse_buffer.length < SEND_MIN)) return;
    if (!navigator.onLine) return;

    sending = true;
    try {
      const events = (window.__mouse_buffer.splice(0, window.__mouse_buffer.length) || []);
      if (!events || events.length === 0) return; // defensive

      const events_sample = events.slice(-500).map(e => ({ x: e.x, y: e.y, t: e.t, type: e.type }));
      const feats = compute_basic_features(events_sample);
      const payload = {
        session_id: window.__mouse_session,
        page: window.location.pathname || (document && document.location && document.location.pathname) || "/",
        ts: Date.now(),
        events_sample,
        features: feats,
        meta: { ua: navigator.userAgent, url: (document && document.location && document.location.href) || "" }
      };

      const { status, ok, data } = await postHandler(ENDPOINT, payload);
      window.__mouse_last_sent = { ts: Date.now(), status, ok, data };

      const isBot = data && (data.result === "bot" || data.label === "bot" || data.prediction?.label === "bot" || data.detection?.result === "bot");
      if (isBot) {
        const score = data.score ?? data.confidence ?? data.prediction?.confidence ?? data.detection?.score ?? 0;
        const reason = data.detail || data.reason || `Bot detected (score=${Number(score).toFixed(3)})`;
        showBlockOverlay(reason);
      }
    } catch (err) {
      console.warn("mouse send failed", err);
    } finally {
      sending = false;
    }
  }

  const _intervalHandle = setInterval(() => trySend(false).catch(()=>{}), BATCH_INTERVAL_MS);

  window.addEventListener("beforeunload", () => trySend(true).catch(()=>{}));
  window.addEventListener("pagehide", () => trySend(true).catch(()=>{}));

  window.__mouse_status = () => ({
    session: window.__mouse_session,
    blocked: !!window.__mouse_blocked,
    buffer_len: (window.__mouse_buffer && window.__mouse_buffer.length) || 0,
    last_sent: window.__mouse_last_sent
  });

  console.info("Mouse dynamics tracker initialized — session:", window.__mouse_session);

  function stopMouseTracker() {
    try {
      clearInterval(_intervalHandle);
      window.__mouse_collector_registered = false;
      window.__mouse_listeners_attached = false;
    } catch (e) { /* ignore */ }
  }

  function detectAutomation() {
    const ua = (navigator.userAgent || "").toLowerCase();
    const badKeywords = ["selenium", "webdriver", "headless", "phantomjs", "puppeteer", "playwright", "automation"];
    if (badKeywords.some(k => ua.includes(k))) return true;
    if (window.__mouse_blocked) return true;
    try {
      if (document.hasFocus && document.hasFocus() && (window.__mouse_buffer || []).length === 0) {
        return false;
      }
    } catch (e) {}
    return false;
  }

  window.__stop_mouse_tracker = stopMouseTracker;
  window.__detect_automation = detectAutomation;

window.__automation = window.__automation || {};
window.__automation.stop = stopMouseTracker;
window.__automation.detect = detectAutomation;


} // end initialization guard

// Final ESM named exports (these work in Vite/react)
export function detectAutomation() {
  try {
    if (typeof window !== "undefined" && typeof window.__detect_automation === "function") {
      return window.__detect_automation();
    }
  } catch (e) {}
  return false;
}

export function stopMouseTracker() {
  try {
    if (typeof window !== "undefined" && typeof window.__stop_mouse_tracker === "function") {
      return window.__stop_mouse_tracker();
    }
  } catch (e) {}
  return undefined;
}

// For backwards compatibility export a postJSON wrapper only when available (not required)
export async function postJSON(url, body) {
  return (postHandler || _postJSON)(url, body);
}

export default {
  detectAutomation,
  stopMouseTracker,
  postJSON
};