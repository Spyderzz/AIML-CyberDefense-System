// frontend/src/pages/Dashboard.jsx
import React, { useEffect, useRef, useState, useCallback } from "react";
import Topbar from "../components/Topbar";
import api, { predictMouse as apiPredictMouse, fetchAlerts as apiFetchAlerts } from "../services/api";
import useMouseDynamics from "../hooks/useMouseDynamics"; // optional: keep if available
import { toast } from "../utils/toast"

/* Dashboard — normalize model responses to botProb (0..1).
   Handles many server response shapes and returns a simple object.
*/

function LovableCard({ title, children, style = {} }) {
  return (
    <section className="lovable-card full-height" style={style}>
      <header className="lovable-card-header">
        <h3>{title}</h3>
      </header>
      <div className="lovable-card-body">{children}</div>
    </section>
  );
}

// helper: coerce many truthy/falsey forms to boolean
function coerceBool(v) {
  if (v === true || v === 1 || v === "1") return true;
  if (v === false || v === 0 || v === "0") return false;
  if (typeof v === "string") {
    const s = v.trim().toLowerCase();
    if (s === "true" || s === "yes" || s === "on") return true;
    if (s === "false" || s === "no" || s === "off") return false;
    const n = Number(s);
    if (!Number.isNaN(n)) return Boolean(n);
  }
  return Boolean(v);
}

// Normalize many server response shapes into {botProb,label,confidenceRaw,raw}
function normalizePredictionResponse(res) {
  if (!res) return { botProb: null, label: null, confidenceRaw: null, raw: res };

  // array-like response
  if (Array.isArray(res) && res.length > 0) {
    const first = res[0];
    // array of objects with label/prob
    if (first && typeof first === "object" && (first.label || first.bot_prob || first.prob || first.score)) {
      const label = first.label || first.prediction || null;
      const candidate = first.bot_prob ?? first.prob ?? first.score ?? first.confidence ?? null;
      const num = (candidate != null && !Number.isNaN(Number(candidate))) ? Number(candidate) : null;
      if (num != null) {
        const lbl = label ? String(label).toLowerCase() : "";
        const botProb = (lbl === "human" && num > 0.5) ? (1 - num) : num;
        return { botProb: Math.max(0, Math.min(1, botProb)), label, confidenceRaw: num, raw: res };
      }
    }

    // array like [label, score]
    if (res.length >= 2) {
      const pred = res[0];
      const sc = res[1];
      const num = (sc != null && !Number.isNaN(Number(sc))) ? Number(sc) : null;
      if (num != null) {
        const lbl = pred ? String(pred).toLowerCase() : "";
        const botProb = (lbl === "bot" || lbl === "1" || lbl === "true") ? num : (lbl === "human" ? 1 - num : num);
        return { botProb: Math.max(0, Math.min(1, botProb)), label: pred, confidenceRaw: num, raw: res };
      }
    }
  }

  // plain number -> assume bot probability (0..1 or 0..100)
  if (typeof res === "number" && !Number.isNaN(res)) {
    let n = Number(res);
    if (n > 1) n = n / 100.0;
    return { botProb: Math.max(0, Math.min(1, n)), label: n >= 0.5 ? "bot" : "human", confidenceRaw: n, raw: res };
  }

  // object/dict cases
  if (typeof res === "object") {
    const obj = res;

    // common fields
    const maybeBot = obj.bot_prob ?? obj.botP ?? obj.botProbability ?? obj.botProbabilityScore;
    const maybeHuman = obj.human_prob ?? obj.humanP ?? obj.humanProbability ?? obj.humanProbabilityScore;
    const maybeConf = obj.confidence ?? obj.score ?? obj.prob ?? obj.probability ?? obj.pred_confidence;

    // use bot_prob if present
    if (maybeBot != null && !Number.isNaN(Number(maybeBot))) {
      const n = Number(maybeBot);
      return { botProb: Math.max(0, Math.min(1, n)), label: obj.label || obj.result || obj.prediction || null, confidenceRaw: n, raw: res };
    }

    // invert human_prob
    if (maybeHuman != null && !Number.isNaN(Number(maybeHuman))) {
      const n = Number(maybeHuman);
      const bot = 1 - n;
      return { botProb: Math.max(0, Math.min(1, bot)), label: obj.label || obj.result || obj.prediction || null, confidenceRaw: n, raw: res };
    }

    // confidence-like field: guess bot vs human
    if (maybeConf != null && !Number.isNaN(Number(maybeConf))) {
      let n = Number(maybeConf);
      if (n > 1) n = n / 100.0;

      const label = (obj.label || obj.prediction || obj.result || "").toString().toLowerCase();

      let botProb = n;
      if (label) {
        if (label === "human" && n > 0.5) botProb = 1 - n;
        else if (label === "bot" && n <= 0.5) {
          botProb = n;
        } else {
          botProb = n;
        }
      } else {
        botProb = n;
      }

      return { botProb: Math.max(0, Math.min(1, botProb)), label: obj.label || obj.prediction || obj.result || null, confidenceRaw: n, raw: res };
    }

    // shapes like { result: "bot", score: 0.72 }
    if ((obj.result || obj.prediction || obj.label) && (obj.score || obj.prob)) {
      const lbl = (obj.result || obj.prediction || obj.label).toString().toLowerCase();
      const s = Number(obj.score ?? obj.prob);
      if (!Number.isNaN(s)) {
        const botProb = (lbl === "bot") ? s : (lbl === "human" ? 1 - s : s);
        return { botProb: Math.max(0, Math.min(1, botProb)), label: obj.result || obj.prediction || obj.label || null, confidenceRaw: s, raw: res };
      }
    }

    // fallback if object is array-like
    if (Array.isArray(obj) && obj.length > 0) {
      return normalizePredictionResponse(obj);
    }

    // last try: numeric fields
    for (const k of ["prob", "score", "confidence", "pred", "value"]) {
      if (obj[k] != null && !Number.isNaN(Number(obj[k]))) {
        const n = Number(obj[k]);
        const nn = n > 1 ? n / 100.0 : n;
        return { botProb: Math.max(0, Math.min(1, nn)), label: obj.label || null, confidenceRaw: nn, raw: res };
      }
    }
  }

  // unknown shape
  return { botProb: null, label: null, confidenceRaw: null, raw: res };
}

export default function Dashboard() {
  // alerts
  const [alerts, setAlerts] = useState([]);
  const [loadingAlerts, setLoadingAlerts] = useState(false);

  // dynamic LiveTrafficChart import
  const [LiveTrafficChartComp, setLiveTrafficChartComp] = useState(null);

  // mouse hook (optional)
  const mouseHook = (typeof useMouseDynamics === "function") ? useMouseDynamics({ intervalMs: 3000, batchLimit: 800, enableSend: true }) : null;

  // canvas & drawing
  const canvasRef = useRef(null);
  const pathRef = useRef([]); // array of {x,y,t}
  const rafRef = useRef(null);

  // prediction state
  const [prediction, setPrediction] = useState({ label: null, score: null, raw: null });
  const [modelLatencyMs, setModelLatencyMs] = useState(null); // round-trip latency
  const [predPercentBot, setPredPercentBot] = useState(null); // 0-100
  const lastSentAtRef = useRef(0);
  const inFlightRef = useRef(false); // avoid overlapping calls
  const bufferRef = useRef([]);

  // session id short debug
  const sessionId = mouseHook && mouseHook.sessionId ? mouseHook.sessionId : null;

  // health & db probe state
  const [health, setHealth] = useState(null);
  const [dbActive, setDbActive] = useState(false);
  const [lastProbe, setLastProbe] = useState(null);
  const [probing, setProbing] = useState(false);

  // load alerts + chart
  useEffect(() => {
    let mounted = true;
    async function loadAlerts() {
      setLoadingAlerts(true);
      try {
        if (typeof apiFetchAlerts === "function") {
          const res = await apiFetchAlerts();
          if (!mounted) return;
          const list = Array.isArray(res) ? res : res?.alerts || [];
          setAlerts(list);
        } else {
          setAlerts([]);
        }
      } catch (e) {
        console.error("fetchAlerts error", e);
        toast("Unable to load alerts", "error", 1400);
      } finally {
        setLoadingAlerts(false);
      }
    }
    loadAlerts();

    // try import chart component dynamically
    (async () => {
      try {
        const candidates = [
          "../components/LiveTrafficChart",
          "../components/LiveTrafficChart.jsx",
          "../components/LiveTrafficChart/index",
        ];
        for (const p of candidates) {
          try {
            // eslint-disable-next-line no-await-in-loop
            const mod = await import(/* @vite-ignore */ p);
            const Comp = mod.default || mod.LiveTrafficChart || mod;
            if (mounted) setLiveTrafficChartComp(() => Comp);
            break;
          } catch (err) {
            // ignore and try next
          }
        }
      } catch (err) {
        // ignore
      }
    })();

    return () => { mounted = false; };
  }, []);

  // handle mouse move for canvas & prediction buffer
  const handleMouseMove = useCallback((e) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const t = Date.now();
    // add to path
    pathRef.current.push({ x, y, t });
    // buffer for prediction (keep last 200)
    bufferRef.current.push({ x, y, t });
    if (bufferRef.current.length > 200) bufferRef.current.shift();
    // throttle: send only if >1000ms since last send
    const now = Date.now();
    if (now - lastSentAtRef.current > 1000) {
      lastSentAtRef.current = now;
      const initialBatchSize = (lastSentAtRef.current === 0) ? 120 : 50;
      const eventsToSend = bufferRef.current.slice(-initialBatchSize).map(ev => ({ x: ev.x, y: ev.y, t: ev.t }));
      sendPrediction(eventsToSend);
    }
    // schedule drawing
    if (!rafRef.current) {
      rafRef.current = requestAnimationFrame(drawPaths);
    }
  }, []);

  // draw function
  const drawPaths = () => {
    rafRef.current = null;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    // clear
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const pts = pathRef.current.slice(-300); // last 300
    if (pts.length <= 0) return;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    // fade older points
    for (let i = 1; i < pts.length; i++) {
      const p0 = pts[i - 1];
      const p1 = pts[i];
      const alpha = Math.max(0.08, (i / pts.length) * 0.9);
      ctx.strokeStyle = `rgba(6,182,212,${(alpha * 0.9).toFixed(2)})`;
      ctx.lineWidth = Math.max(1 + (i / pts.length) * 4, 1);
      ctx.beginPath();
      ctx.moveTo(p0.x, p0.y);
      ctx.lineTo(p1.x, p1.y);
      ctx.stroke();
    }
  };

  // resize canvas to match layout
  useEffect(() => {
    function resize() {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(320, Math.floor(rect.width * ratio));
      canvas.height = Math.max(180, Math.floor(rect.height * ratio));
      canvas.style.width = rect.width + "px";
      canvas.style.height = rect.height + "px";
      // scale context
      const ctx = canvas.getContext("2d");
      ctx && ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    }
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  // attach mouse listener to visualizer area
  useEffect(() => {
    const container = document.getElementById("mouse-visualizer-area");
    if (!container) return () => {};
    container.addEventListener("mousemove", handleMouseMove);
    return () => {
      container.removeEventListener("mousemove", handleMouseMove);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [handleMouseMove]);

  // send prediction to API — measure latency and parse prob
  async function sendPrediction(events) {
    // avoid overlapping
    if (inFlightRef.current) return;
    inFlightRef.current = true;

    // start time
    const t0 = performance.now ? performance.now() : Date.now();
    let timedOut = false;
    const TIMEOUT_MS = 5000;
    const timeoutId = setTimeout(() => {
      timedOut = true;
      inFlightRef.current = false;
      setModelLatencyMs(Math.round((performance.now ? performance.now() : Date.now()) - t0));
      console.warn("predict: client-side timeout");
    }, TIMEOUT_MS);

    try {
      if (typeof apiPredictMouse === "function") {
        const res = await apiPredictMouse(events);

        if (timedOut) {
          console.warn("predict: late response ignored");
          clearTimeout(timeoutId);
          return;
        }

        const t1 = performance.now ? performance.now() : Date.now();
        const latency = Math.round(t1 - t0);

        // debug raw response
        console.debug("predict response raw:", res);

        // prefer server latency if given
        if (res && (res._server_latency_ms != null)) {
          const s = Number(res._server_latency_ms);
          if (!Number.isNaN(s)) setModelLatencyMs(Math.round(s));
          else setModelLatencyMs(latency);
        } else {
          setModelLatencyMs(latency);
        }

        if (!res) {
          setPrediction({ label: null, score: null, raw: res });
          setPredPercentBot(null);
          return;
        }

        // normalize response
        const norm = normalizePredictionResponse(res);

        const botProbNormalized = (norm.botProb != null && !Number.isNaN(Number(norm.botProb))) ? Number(norm.botProb) : null;
        const labelNormalized = norm.label || (res.label || res.prediction || null);
        const confRaw = norm.confidenceRaw != null ? Number(norm.confidenceRaw) : (res.confidence ?? res.score ?? res.prob ?? null);

        if (botProbNormalized != null) {
          const clamped = Math.max(0, Math.min(1, botProbNormalized));
          setPredPercentBot(Math.round(clamped * 100));
          setPrediction({ label: labelNormalized, score: clamped, raw: res });
        } else {
          // fallback heuristics
          let fallbackLabel = res.label || res.prediction || null;
          let fallbackScore = res.score ?? res.prob ?? res.confidence ?? null;
          if (fallbackScore != null && !Number.isNaN(Number(fallbackScore))) {
            let s = Number(fallbackScore);
            if (s > 1) s = s / 100.0;
            const lbl = fallbackLabel ? String(fallbackLabel).toLowerCase() : "";
            let bp = s;
            if (lbl === "human") bp = 1 - s;
            setPredPercentBot(Math.round(Math.max(0, Math.min(1, bp)) * 100));
            setPrediction({ label: fallbackLabel, score: bp, raw: res });
          } else {
            // try top-level bot_prob/human_prob
            if (res.bot_prob != null) {
              const n = Number(res.bot_prob);
              const cl = Math.round(Math.max(0, Math.min(1, n)) * 100);
              setPredPercentBot(cl);
              setPrediction({ label: res.label || null, score: n, raw: res });
            } else if (res.human_prob != null) {
              const n = 1 - Number(res.human_prob);
              const cl = Math.round(Math.max(0, Math.min(1, n)) * 100);
              setPredPercentBot(cl);
              setPrediction({ label: res.label || null, score: n, raw: res });
            } else {
              setPredPercentBot(null);
              setPrediction({ label: null, score: null, raw: res });
            }
          }
        }
      } else if (api && typeof api.predictCombined === "function") {
        const t0b = performance.now ? performance.now() : Date.now();
        const res = await api.predictCombined({ mouse: { events } });
        const t1b = performance.now ? performance.now() : Date.now();
        // prefer server latency
        if (res && res._server_latency_ms != null) {
          const s = Number(res._server_latency_ms);
          if (!Number.isNaN(s)) setModelLatencyMs(Math.round(s));
          else setModelLatencyMs(Math.round(t1b - t0b));
        } else {
          setModelLatencyMs(Math.round(t1b - t0b));
        }
        const norm = normalizePredictionResponse(res);
        if (norm.botProb != null) {
          setPredPercentBot(Math.round(norm.botProb * 100));
        } else {
          setPredPercentBot(null);
        }
        setPrediction({ label: norm.label || res.label || null, score: norm.botProb ?? res.score ?? null, raw: res });
      } else {
        // no endpoint
      }
    } catch (err) {
      const t1 = performance.now ? performance.now() : Date.now();
      setModelLatencyMs(Math.round(t1 - t0));
      console.error("predict error", err);
      if (!window.__DASH_PRED_ERR_SHOWN__) {
        window.__DASH_PRED_ERR_SHOWN__ = true;
        toast("Prediction endpoint unreachable", "error", 1400);
      }
      setPredPercentBot(null);
    } finally {
      clearTimeout(timeoutId);
      inFlightRef.current = false;
    }
  }

  // System health probe URLs (dev)
  const HEALTH_URL = "http://localhost:5000/health";
  const ALERTS_URL = "http://localhost:5000/api/alerts";

  const fetchHealth = useCallback(async () => {
    try {
      const r = await fetch(HEALTH_URL, { credentials: "same-origin" });
      const text = await r.text();
      // try parse JSON
      try {
        const j = JSON.parse(text);
        if (!r.ok) {
          const errObj = { error: `Status ${r.status} ${r.statusText}`, body: j };
          setHealth(errObj);
          return errObj;
        }
        setHealth(j);
        return j;
      } catch (err) {
        // not JSON — keep raw text
        const errorObj = { error: `Health endpoint didn't return JSON (status ${r.status}).`, rawText: text, status: r.status };
        setHealth(errorObj);
        return errorObj;
      }
    } catch (err) {
      const errObj = { error: String(err) };
      setHealth(errObj);
      return errObj;
    }
  }, []);

  const probeDb = useCallback(async () => {
    try {
      const start = performance.now();
      const res = await fetch(ALERTS_URL, { method: "GET", credentials: "same-origin" });
      const took = Math.round(performance.now() - start);
      if (res.status === 200 || res.status === 401 || res.status === 403) {
        setDbActive(true);
        setLastProbe({ time: new Date().toLocaleString(), detail: `${res.status} ${res.statusText}`, took });
      } else {
        setDbActive(false);
        setLastProbe({ time: new Date().toLocaleString(), detail: `${res.status} ${res.statusText}`, took });
      }
    } catch (err) {
      setDbActive(false);
      setLastProbe({ time: new Date().toLocaleString(), detail: `Network: ${String(err)}`, took: null });
    }
  }, []);

  const runProbeAll = useCallback(async () => {
    setProbing(true);
    await fetchHealth();
    await probeDb();
    setProbing(false);
  }, [fetchHealth, probeDb]);

  useEffect(() => {
    runProbeAll();
    const t1 = setInterval(() => fetchHealth(), 20_000);
    const t2 = setInterval(() => probeDb(), 45_000);
    return () => {
      clearInterval(t1);
      clearInterval(t2);
    };
  }, [fetchHealth, probeDb, runProbeAll]);

  // derive statuses
  const ddosActive = Boolean(health) && coerceBool((health && health.flow_rf) || false) && coerceBool((health && health.flow_xgb) || false);
  const botActive = Boolean(health) && coerceBool((health && health.mouse_lstm) || false) && coerceBool((health && health.mouse_rf) || false);
  const systemOk = Boolean(health) && (typeof (health && health.status) === "string" ? (health.status || "").toLowerCase() === "ok" : coerceBool((health && health.status) || false));

  // small UI helpers
  function renderPredictionBadge() {
    // show percent if we have it
    if (predPercentBot != null) {
      const isBot = predPercentBot >= 90;
      const color = isBot ? "#ff6b6b" : "#34d399";
      return (
        <div style={{ display: "flex", gap: 12, alignItems: "center", fontSize: 13 }}>
          <div style={{ padding: "6px 10px", borderRadius: 8, background: color, color: "#062023", fontWeight: 700 }}>
            {isBot ? "Bot" : "Human"}
          </div>
          
          
        </div>
      );
    }

    // fallback to label/score
    const label = (prediction && prediction.label) ? String(prediction.label).toLowerCase() : null;
    const score = prediction && prediction.score != null ? Number(prediction.score).toFixed(3) : null;
    if (!label && score == null) {
      return <div className="muted">No prediction yet — move your mouse to generate.</div>;
    }
    const isBot = label === "bot" || label === "1" || label === "true";
    const color = isBot ? "#ff6b6b" : "#34d399";
    return (
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <div style={{ padding: "6px 12px", borderRadius: 8, background: color, color: "#062023", fontWeight: 700 }}>
          {isBot ? "Bot" : "Human"}
        </div>
        <div style={{ color: "#9fb0c8" }}>
          {score != null ? <span>score: <strong style={{ color: "#fff" }}>{score}</strong></span> : null}
        </div>
      </div>
    );
  }

  // render latency and score under canvas
  function renderLatencyAndScore() {
    if (predPercentBot != null || modelLatencyMs != null) {
      return (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", color: "#9aa6b9", fontSize: 13 }}>
          <div>
            {modelLatencyMs != null ? <span>Model latency: <strong style={{ color: "#fff" }}>{modelLatencyMs} ms</strong></span> : <span>&nbsp;</span>}
          </div>
          <div>
            {predPercentBot != null ? (
              <span>Human: <strong style={{ color: "#fff" }}>{predPercentBot}%</strong> &nbsp; • &nbsp; Bot: <strong style={{ color: "#fff" }}>{100 - predPercentBot}%</strong></span>
            ) : (
              <span className="muted">No numeric score yet</span>
            )}
          </div>
        </div>
      );
    }
    return <div className="muted">No prediction yet — move your mouse to generate.</div>;
  }

  // UI (layout unchanged)
  return (
    <div className="page-root">
      <Topbar />
      <main className="dashboard-fullscreen">
        <div className="dashboard-split">
          {/* LEFT: Live Alerts + Live Traffic Chart + system health inside left column */}
          <div className="split-left">
            <LovableCard title="Live Alerts">
              <div style={{ marginBottom: 12 }}>
                {loadingAlerts ? <div className="muted">Loading alerts...</div> : alerts.length === 0 ? <div className="muted">No active alerts</div> :
                  <ul className="alerts-list">
                    {alerts.map((a, i) => (
                      <li key={a.id || i} className="alert-item">
                        <div className="alert-title">{a.title || a.message || `Alert #${i + 1}`}</div>
                        <div className="alert-meta">{a.time || a.timestamp || ""}</div>
                      </li>
                    ))}
                  </ul>
                }
              </div>

              <div style={{ marginTop: 8 }}>
                {LiveTrafficChartComp ? (
                  <div style={{ height: 260 }}>
                    <LiveTrafficChartComp />
                  </div>
                ) : (
                  <div className="muted">Live traffic chart not found. Place your LiveTrafficChart component in src/components.</div>
                )}
              </div>

              <div style={{ marginTop: 18 }}>
                <div className="status-inside-left">
                  <h3 className="status-card-title">System Health & Modules</h3>

                  <div className="service-item">
                    <div className="service-text">
                      <div className="status-label">DDoS Detection<span className="status-sub"></span></div>
                      <div className="status-sub small">Flow RF / XGB</div>
                    </div>
                    <div className="status-badge">
                      <span className={`dot ${ddosActive ? "green" : "red"}`} />
                      <div className="status-sub-right">{ddosActive ? "Active" : "Inactive"}</div>
                    </div>
                  </div>

                  <div className="service-item">
                    <div className="service-text">
                      <div className="status-label">Bot Detection<span className="status-sub"></span></div>
                      <div className="status-sub small">Mouse LSTM / RF</div>
                    </div>
                    <div className="status-badge">
                      <span className={`dot ${botActive ? "green" : "red"}`} />
                      <div className="status-sub-right">{botActive ? "Active" : "Inactive"}</div>
                    </div>
                  </div>

                  <div className="service-item">
                    <div className="service-text">
                      <div className="status-label">Database System<span className="status-sub"></span></div>
                      
                    </div>
                    <div className="status-badge">
                      <span className={`dot ${dbActive ? "green" : "red"}`} />
                      <div className="status-sub-right">{dbActive ? "Active" : "Offline"}</div>
                    </div>
                  </div>

                  <div className="service-item">
                    <div className="service-text">
                      <div className="status-label" style={{ fontWeight: 700 }}>CyberDefense System {systemOk ? "" : "Offline / Degraded"}</div>
                    </div>
                    <div className="status-badge">
                      <span className={`dot ${systemOk ? "green" : "red"}`} />
                      <div className="status-sub-right">{systemOk ? "Running" : "Offline"}</div>
                    </div>
                  </div>

                 <div className="muted small">
  {lastProbe ? (
    <>
      Last ping: {lastProbe.time}<br />
      Status: {lastProbe.detail}<br />
      Latency: {lastProbe.took}ms
    </>
  ) : (
    "No probes yet"
  )}
</div>

                  <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                    <button className="btn" onClick={() => runProbeAll()} disabled={probing}>{probing ? "Probing…" : "Refresh"}</button>
                    <button className="btn ghost" onClick={() => fetchHealth()} style={{ marginLeft: 4 }}>Refresh /health</button>
                    <button className="btn ghost" onClick={() => probeDb()} style={{ marginLeft: 4 }}>Ping DB</button>
                  </div>
                </div>
              </div>
            </LovableCard>
          </div>

          {/* RIGHT: Mouse visualizer + prediction */}
          <div className="split-right">
            <LovableCard title="Mouse Tracker Visualizer">
              <div id="mouse-visualizer-area" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div className="muted">{sessionId ? `Session id: ${sessionId}` : "Interactive visualizer"}</div>
                  <div>{renderPredictionBadge()}</div>
                </div>

                <div style={{ flex: 1, minHeight: 220, display: "flex", gap: 12 }}>
                  <canvas ref={canvasRef} style={{ width: "100%", height: 220, borderRadius: 8, background: "transparent" }} />
                </div>

                <div style={{ fontSize: 13 }}>
                  {renderLatencyAndScore()}
                </div>
              </div>
            </LovableCard>
          </div>
        </div>
      </main>
    </div>
  );
}