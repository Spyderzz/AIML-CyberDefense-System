// frontend/src/hooks/useMouseDynamics.js
import { useEffect, useRef, useState } from "react";
import { sendMouseBatch } from "../services/api";


export function computeMouseFeatures(events = []) {
  if (!events || events.length < 2) {
    return {
      count: events.length || 0,
      avg_velocity: 0, median_velocity: 0, max_velocity: 0,
      avg_acc: 0, max_acc: 0, std_acc: 0,
      curvature_mean: 0, curvature_std: 0,
      pause_count: 0, longest_pause: 0, pct_pause_time: 0,
      path_length: 0, euclidean_distance: 0, tortuosity: 0, smoothness_index: 0, jerk_std: 0,
      mean_angle: 0, angle_std: 0,
      click_count: 0, avg_dwell_before_click: 0, avg_time_between_clicks: 0, click_speed: 0,
      total_time_ms: 0
    };
  }

  const mean = arr => arr.length ? arr.reduce((s,x)=>s+x,0)/arr.length : 0;
  const variance = arr => {
    if (!arr.length) return 0;
    const m = mean(arr);
    return arr.reduce((s,x)=>s + (x-m)*(x-m),0)/arr.length;
  };
  const std = arr => Math.sqrt(variance(arr));
  const median = arr => {
    if (!arr.length) return 0;
    const s = [...arr].sort((a,b)=>a-b);
    const mid = Math.floor(s.length/2);
    return (s.length%2) ? s[mid] : (s[mid-1]+s[mid])/2;
  };

  const velocities = [], accs = [], dt_ms_arr = [], angles = [], angle_diffs = [];
  const click_ts = [], dwell_before_clicks = [], speeds_before_clicks = [];
  let path_length = 0;
  let prev = events[0];
  let lastAngle = null;
  const PAUSE_THRESHOLD_MS = 200;
  let pause_count = 0, pause_time_sum = 0, longest_pause = 0;

  for (let i=1;i<events.length;i++){
    const e = events[i];
    let dt_ms = e.t - prev.t;
    if (!dt_ms || dt_ms <= 0) dt_ms = 1;
    dt_ms_arr.push(dt_ms);
    const dx = e.x - prev.x;
    const dy = e.y - prev.y;
    const dist = Math.sqrt(dx*dx + dy*dy);
    path_length += dist;

    const vel = dist / (dt_ms / 1000);
    velocities.push(vel);

    // acceleration 
    if (velocities.length > 1) {
      const a = (velocities[velocities.length-1] - velocities[velocities.length-2]) / ((dt_ms || 1)/1000);
      accs.push(a);
    }

    // angle 
    const ang = Math.atan2(dy, dx);
    angles.push(ang);
    if (lastAngle !== null) {
      let d = ang - lastAngle;
      while (d > Math.PI) d -= 2*Math.PI;
      while (d < -Math.PI) d += 2*Math.PI;
      angle_diffs.push(d);
    }
    lastAngle = ang;

    // pauses
    if (dt_ms >= PAUSE_THRESHOLD_MS) {
      pause_count += 1;
      pause_time_sum += dt_ms;
      if (dt_ms > longest_pause) longest_pause = dt_ms;
    }

    // clicks/dwell detection
    if (e.type === "click") {
      click_ts.push(e.t);
      const dwell = dt_ms;
      if (dwell && dwell > 0) dwell_before_clicks.push(dwell);
      if (velocities.length) speeds_before_clicks.push(velocities[velocities.length-1]);
    }

    prev = e;
  }

  const avg_velocity = mean(velocities);
  const median_velocity = median(velocities);
  const max_velocity = velocities.length ? Math.max(...velocities) : 0;
  const avg_acc = accs.length ? mean(accs) : 0;
  const max_acc = accs.length ? Math.max(...accs) : 0;
  const std_acc = std(accs);

  // curvature approximated via angle diffs / distance
  const curvatures = [];
  for (let i=0;i<angle_diffs.length;i++){
    const dd = Math.abs(angle_diffs[i]);
    const ddist = (dt_ms_arr[i] || 1)/1000;
    curvatures.push(dd / (ddist || 1));
  }
  const curvature_mean = mean(curvatures);
  const curvature_std = std(curvatures);
  const euclidean = Math.sqrt((events[events.length-1].x - events[0].x)**2 + (events[events.length-1].y - events[0].y)**2);
  const tortuosity = euclidean > 0 ? (path_length / euclidean) : 1;

  // jerk
  const jerk_samples = [];
  for (let i=1;i<accs.length;i++){
    const da = accs[i] - accs[i-1];
    const dt_s = (dt_ms_arr[i+1] || dt_ms_arr[i] || 1)/1000;
    jerk_samples.push(Math.abs(da)/(dt_s||1e-3));
  }
  const jerk_std = std(jerk_samples);
  const smoothness_index = 1 / (1 + jerk_std);

  let mean_angle = 0, angle_std = 0;
  if (angles.length){
    let sx=0, sy=0;
    for (const a of angles){ sx += Math.cos(a); sy += Math.sin(a); }
    mean_angle = Math.atan2(sy, sx);
    const R = Math.sqrt(sx*sx + sy*sy)/angles.length;
    angle_std = Math.sqrt(Math.max(0, -2*Math.log(R || 1e-9)));
  }

  const click_count = click_ts.length;
  const avg_dwell_before_click = dwell_before_clicks.length ? mean(dwell_before_clicks) : 0;
  const avg_time_between_clicks = click_ts.length > 1 ? mean(click_ts.slice(1).map((t,i)=>t-click_ts[i])) : 0;
  const click_speed = speeds_before_clicks.length ? mean(speeds_before_clicks) : 0;

  const total_time_ms = events[events.length-1].t - events[0].t;
  const pct_pause_time = total_time_ms > 0 ? (pause_time_sum / total_time_ms) : 0;

  return {
    count: events.length,
    avg_velocity, median_velocity, max_velocity,
    avg_acc, max_acc, std_acc,
    curvature_mean, curvature_std,
    pause_count, longest_pause, pct_pause_time,
    path_length, euclidean_distance: euclidean, tortuosity, smoothness_index, jerk_std,
    mean_angle, angle_std,
    click_count, avg_dwell_before_click, avg_time_between_clicks, click_speed,
    total_time_ms
  };
}


// Hook: useMouseDynamics

export function useMouseDynamics({
  intervalMs = 3000,
  batchLimit = 800,
  serverUrl = "/api/collect_mouse",
  enableSend = true
} = {}) {
  const bufferRef = useRef([]);
  const sessionRef = useRef("s_" + Math.floor(Date.now()/1000));
  const strikeRef = useRef(0);
  const lastServerResRef = useRef(null);
  const [blocked, setBlocked] = useState(false);
  const sendingRef = useRef(false);
  const pollRef = useRef(null);
  const localTrackerRef = useRef(false);

  useEffect(() => {
    // If a global collector (utils/automation.js) has registered itself, piggyback on it.
    const globalCollector = typeof window !== "undefined" && !!window.__mouse_collector_registered;

    if (globalCollector) {
      if (window.__mouse_session) sessionRef.current = window.__mouse_session;

      pollRef.current = setInterval(() => {
        try {
          if (typeof window.__mouse_status === "function") {
            const s = window.__mouse_status();
            if (s) {
              setBlocked(!!s.blocked);
              lastServerResRef.current = s.lastServerRes || lastServerResRef.current;
              if (typeof s.strikes === "number") strikeRef.current = s.strikes;
            }
          } else {
            setBlocked(!!localStorage.getItem("mouse_blocked"));
          }
        } catch (e) {
        }
      }, Math.max(1000, intervalMs));

      localTrackerRef.current = false;
      return () => {
        if (pollRef.current) clearInterval(pollRef.current);
      };
    }

    localTrackerRef.current = true;
    window.__mouse_buffer = window.__mouse_buffer || [];
    window.__mouse_session = window.__mouse_session || sessionRef.current;
    sessionRef.current = window.__mouse_session;
    window.__mouse_collector_registered = true;

    const pushEvent = (evt) => {
      try {
        const x = evt.clientX ?? (evt.touches && evt.touches[0] && evt.touches[0].clientX) ?? 0;
        const y = evt.clientY ?? (evt.touches && evt.touches[0] && evt.touches[0].clientY) ?? 0;
        const rec = { x: Math.round(x), y: Math.round(y), t: Date.now(), type: evt.type };
        bufferRef.current.push(rec);
        try { if (typeof window.__mouse_push === "function") window.__mouse_push(rec); } catch(e) {}
        if (bufferRef.current.length > batchLimit) {
          bufferRef.current.splice(0, bufferRef.current.length - batchLimit);
        }
      } catch (e) {
      }
    };

    const clickHandler = (evt) => {
      try {
        const x = evt.clientX ?? 0;
        const y = evt.clientY ?? 0;
        const rec = { x: Math.round(x), y: Math.round(y), t: Date.now(), type: "click" };
        bufferRef.current.push(rec);
        try { if (typeof window.__mouse_push === "function") window.__mouse_push(rec); } catch(e) {}
        if (bufferRef.current.length > batchLimit) bufferRef.current.shift();
      } catch(e){}
    };

    window.addEventListener("mousemove", pushEvent, { passive: true });
    window.addEventListener("touchmove", pushEvent, { passive: true });
    window.addEventListener("mousedown", clickHandler, { passive: true });
    window.addEventListener("mouseup", clickHandler, { passive: true });
    window.addEventListener("click", clickHandler, { passive: true });

    const timer = setInterval(async () => {
      if (!enableSend || sendingRef.current) return;
      if (!bufferRef.current || bufferRef.current.length === 0) return;

      sendingRef.current = true;
      try {
        const eventsToSend = bufferRef.current.slice();
        bufferRef.current.splice(0, bufferRef.current.length);

        const features = computeMouseFeatures(eventsToSend);
        const payload = {
          session_id: sessionRef.current,
          page: window.location.pathname,
          ts: Date.now(),
          events_sample: eventsToSend.slice(-500),
          features,
          meta: { ua: navigator.userAgent, url: window.location.href }
        };

        const res = await sendMouseBatch(payload).catch(err => {
          return null;
        });

        if (res) lastServerResRef.current = res;

        const detectedBot = res && (res.result === "bot" || (res.prediction && res.prediction.label === "bot") || res.label === "bot" || (res.detection && res.detection.result === "bot"));
        if (detectedBot) {
          strikeRef.current += 1;
        } else {
          strikeRef.current = 0;
        }

        if (strikeRef.current >= 2) {
          setBlocked(true);
          try { localStorage.setItem("mouse_blocked", "1"); } catch(e) {}
        } else {
          setBlocked(false);
        }
      } catch (e) {
      } finally {
        sendingRef.current = false;
      }
    }, Math.max(1000, intervalMs));

    return () => {
      clearInterval(timer);
      window.removeEventListener("mousemove", pushEvent);
      window.removeEventListener("touchmove", pushEvent);
      window.removeEventListener("mousedown", clickHandler);
      window.removeEventListener("mouseup", clickHandler);
      window.removeEventListener("click", clickHandler);
      try { window.__mouse_collector_registered = false; } catch(e) {}
    };
  }, [intervalMs, batchLimit, enableSend, serverUrl]);

  useEffect(() => {
    window.__mouse_status = () => ({
      session_id: sessionRef.current,
      buffer_len: (bufferRef.current && bufferRef.current.length) || 0,
      lastServerRes: lastServerResRef.current,
      strikes: strikeRef.current,
      blocked
    });
  }, [blocked]);

  function unblock() {
    strikeRef.current = 0;
    setBlocked(false);
    try { localStorage.removeItem("mouse_blocked"); } catch(e) {}
    try {
      sendMouseBatch({ session_id: sessionRef.current, meta: { action: "recheck" } }).catch(()=>{});
    } catch(e) {}
  }

  return {
    blocked,
    unblock
  };
}

export default useMouseDynamics;