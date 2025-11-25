// frontend/src/flow_report.js

(function (root) {
  if (!root) return;
  if (root.__flow_collector_registered) {
    console.debug("flow_report: already registered");
    return;
  }
  root.__flow_collector_registered = true;

  const API_PATH = (typeof IMPORT_META_API_BASE !== "undefined" ? IMPORT_META_API_BASE : "") || "";

  const CONF = {
    sendIntervalMs: 3000,
    batchLimit: 1200,
    sampleMouse: true,
    sendUrl: "/api/collect_mouse", 
    predict: false,
    sessionPrefix: "s_",
  };

  const state = {
    sessionId: CONF.sessionPrefix + Math.floor(Date.now() / 1000) + "_" + Math.random().toString(36).slice(2, 8),
    buffer: [],
    lastSend: null,
    lastResponse: null,
    blocked: false,
    strikes: 0,
    sending: false,
  };


  function now() { return Date.now(); }
  function safeFetch(url, opts) {
    try {
      return fetch(url, opts);
    } catch (e) {
      return Promise.reject(e);
    }
  }


  function pushEvent(e) {
    try {
      const rec = { x: e.clientX || 0, y: e.clientY || 0, t: now(), type: e.type || "move" };
      state.buffer.push(rec);
      if (state.buffer.length > CONF.batchLimit) state.buffer.splice(0, state.buffer.length - CONF.batchLimit);
    } catch (e) {
      
    }
  }
  function clickHandler(e) {
    try {
      const rec = { x: e.clientX || 0, y: e.clientY || 0, t: now(), type: "click" };
      state.buffer.push(rec);
      if (state.buffer.length > CONF.batchLimit) state.buffer.shift();
    } catch (e) {}
  }

  // simple sample to keep payload small
  function sampleEvents(arr, max = 300) {
    if (!arr || arr.length <= max) return arr.slice();
    
    return arr.slice(-max);
  }

  // send function
  async function sendBatch(extra = {}) {
    if (state.sending) return null;
    if (!state.buffer || state.buffer.length === 0) return null;
    state.sending = true;
    const eventsToSend = sampleEvents(state.buffer, 500);
    // clear sent items from buffer
    try {
      state.buffer.splice(0, eventsToSend.length);
    } catch (e) {}

    const payload = {
      session_id: state.sessionId,
      events: eventsToSend,
      meta: {
        ua: navigator.userAgent,
        url: location.href,
        page: location.pathname,
        ts: now(),
        ...extra.meta
      },
      predict: typeof extra.predict === "boolean" ? extra.predict : CONF.predict
    };

    try {
      const res = await safeFetch(API_PATH + CONF.sendUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload)
      });
      state.lastSend = now();
      if (!res.ok) {
        const text = await res.text().catch(()=>null);
        state.lastResponse = { ok:false, status: res.status, bodyText: text };
        state.sending = false;
        return state.lastResponse;
      }
      const body = await res.json().catch(()=>null);
      state.lastResponse = { ok:true, status: res.status, body };
      
      try {
        const label = body && (body.label || body.prediction?.label || body.result || (body.detection && body.detection.result));
        const prob = body && (body.prob_attack || body.prob || body.confidence || body.score);
        const isAttack = (label && String(label).toLowerCase().includes("attack")) || (String(label).toLowerCase().includes("bot")) || (typeof prob === "number" && prob >= 0.5);
        if (isAttack) {
          state.strikes += 1;
        } else {
          state.strikes = Math.max(0, state.strikes - 1);
        }
        if (state.strikes >= 2) {
          state.blocked = true;
          
          try {
            
            const id = "__flow_block_overlay";
            if (!document.getElementById(id)) {
              const ov = document.createElement("div");
              ov.id = id;
              ov.style.position = "fixed";
              ov.style.left = "0";
              ov.style.top = "0";
              ov.style.right = "0";
              ov.style.bottom = "0";
              ov.style.zIndex = "2147483647";
              ov.style.background = "rgba(0,0,0,0.65)";
              ov.style.color = "white";
              ov.style.display = "flex";
              ov.style.alignItems = "center";
              ov.style.justifyContent = "center";
              ov.style.fontSize = "20px";
              ov.innerText = "Access blocked: suspicious activity detected. Contact admin.";
              document.body.appendChild(ov);
            }
          } catch(e) {}
        }
      } catch (e) {}

      return state.lastResponse;
    } catch (err) {
      state.lastResponse = { ok:false, err: String(err) };
      return state.lastResponse;
    } finally {
      state.sending = false;
    }
  }

  
  let senderTimer = null;
  function startSender() {
    if (senderTimer) return;
    senderTimer = setInterval(() => {
      try {
        sendBatch().catch(()=>{});
      } catch (e) {}
    }, Math.max(1000, CONF.sendIntervalMs));
  }
  function stopSender() {
    if (senderTimer) { clearInterval(senderTimer); senderTimer = null; }
  }

  // start listeners
  function startListeners() {
    if (state.listenersActive) return;
    window.addEventListener("mousemove", pushEvent, { passive: true });
    window.addEventListener("mousedown", clickHandler, { passive: true });
    window.addEventListener("mouseup", clickHandler, { passive: true });
    window.addEventListener("click", clickHandler, { passive: true });
    state.listenersActive = true;
  }
  function stopListeners() {
    try {
      window.removeEventListener("mousemove", pushEvent);
      window.removeEventListener("mousedown", clickHandler);
      window.removeEventListener("mouseup", clickHandler);
      window.removeEventListener("click", clickHandler);
    } catch (e) {}
    state.listenersActive = false;
  }

  // expose API on window
  root.__flow_collector = {
    config: CONF,
    getState: () => Object.assign({}, state),
    start: () => { startListeners(); startSender(); return true; },
    stop: () => { stopSender(); stopListeners(); return true; },
    sendNow: (extra) => sendBatch(extra).catch(e=>({ok:false,err:String(e)})),
    unblock: () => { state.strikes = 0; state.blocked = false; try { const el = document.getElementById("__flow_block_overlay"); if (el) el.remove(); } catch(e){}; },
    sessionId: state.sessionId,
  };

  // simple status helper function
  root.__flow_collector_status = function () {
    return {
      sessionId: state.sessionId,
      bufferLength: state.buffer.length,
      lastSend: state.lastSend,
      lastResponse: state.lastResponse,
      blocked: state.blocked,
      strikes: state.strikes,
      listeners: !!state.listenersActive
    };
  };

  // auto-start by default
  try {
    startListeners();
    startSender();
    console.debug("flow_report: collector started session:", state.sessionId);
  } catch (e) {
    console.warn("flow_report: failed to start:", e);
  }

})(typeof window !== "undefined" ? window : null);