// frontend/src/components/MouseVisualizer.jsx
import React, { useEffect, useRef, useState } from "react";
import { collectMouse } from "../services/api";

function computeDerived(events) {
  if (!events || events.length < 2) return {};
  let last = null;
  const speeds = [];
  const accs = [];
  const angles = [];
  const dt_arr = [];
  const clicks = events.filter(e => e.type === "click").length;
  for (let i=0;i<events.length;i++){
    const e = events[i];
    if (!last) { last = e; continue; }
    const dx = e.x - last.x;
    const dy = e.y - last.y;
    const dt = (e.t - last.t) / 1000 || 0.001;
    const speed = Math.sqrt(dx*dx + dy*dy) / dt;
    speeds.push(speed);
    dt_arr.push(dt);
    if (speeds.length>1) accs.push((speeds[speeds.length-1]-speeds[speeds.length-2])/dt);
    const ang = Math.atan2(dy, dx);
    angles.push(ang);
    last = e;
  }
  const avg = arr => arr.length ? arr.reduce((a,b)=>a+b,0)/arr.length : 0;
  const std = arr => {
    if (!arr.length) return 0;
    const m = avg(arr);
    return Math.sqrt(arr.reduce((s,x)=>s+(x-m)*(x-m),0)/arr.length);
  };
  const angleDiffs = [];
  for (let i=1;i<angles.length;i++){
    let da = angles[i]-angles[i-1];
    while (da <= -Math.PI) da += 2*Math.PI;
    while (da > Math.PI) da -= 2*Math.PI;
    angleDiffs.push(Math.abs(da));
  }
  const curvature = std(angleDiffs);
  return {
    avg_speed: avg(speeds) || 0,
    std_speed: std(speeds) || 0,
    max_speed: speeds.length ? Math.max(...speeds) : 0,
    avg_acc: accs.length ? (accs.reduce((s,v)=>s+v,0)/accs.length) : 0,
    std_acc: std(accs),
    curvature: curvature || 0,
    clicks,
    event_count: events.length,
    avg_dt: dt_arr.length ? (dt_arr.reduce((s,v)=>s+v,0)/dt_arr.length) : 0
  };
}


export default function MouseVisualizer({ points: propPoints = null, canvasHeight = 300 }) {
  const canvasRef = useRef(null);
  const [events, setEvents] = useState([]);           
  const [sessionId, setSessionId] = useState("s_"+Math.floor(Date.now()/1000));
  const [stats, setStats] = useState({});
  const drawRef = useRef({ mounted: false });

  const getCurrentPoints = () => (propPoints && Array.isArray(propPoints) ? propPoints : events);

  useEffect(()=>{
    window.__mouse_viz_push = (evt) => {
      setEvents(prev => {
        const next = prev.length ? prev.concat(evt) : Array.isArray(evt) ? [...evt] : prev;
        if (next.length > 2000) next.splice(0, next.length - 2000);
        setStats(computeDerived(next));
        return next;
      });
    };
    return () => { window.__mouse_viz_push = null; };
  }, []);

  useEffect(()=>{
    if (propPoints && Array.isArray(propPoints)) {
      setStats(computeDerived(propPoints));
    }
  }, [propPoints]);

  useEffect(()=>{
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let mounted = true;
    drawRef.current.mounted = true;

    function resize() {
      const rect = canvas.getBoundingClientRect();
      const dPR = window.devicePixelRatio || 1;
      canvas.width = Math.max(300, Math.floor(rect.width * dPR));
      canvas.height = Math.max(150, Math.floor(canvasHeight * dPR));
      canvas.style.width = rect.width + "px";
      canvas.style.height = canvasHeight + "px";
      ctx.setTransform(dPR, 0, 0, dPR, 0, 0);
    }
    
    resize();
    
    const tick = () => {
      if (!mounted) return;
      const pts = getCurrentPoints();
      
      ctx.clearRect(0,0,canvas.width, canvas.height);
      
      ctx.fillStyle = "rgba(7,20,34,0.12)";
      ctx.fillRect(0,0,canvas.width, canvas.height);

      if (!pts || !pts.length) {
        ctx.fillStyle = "#9aa6b2";
        ctx.font = "12px Arial";
        ctx.fillText("No mouse events captured yet. Start tracking to see visualization.", 12, 20);
      } else {
        
        const xs = pts.map(p=>p.x);
        const ys = pts.map(p=>p.y);
        const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
        const pad = 12;
        const w = Math.max(1, maxX - minX);
        const h = Math.max(1, maxY - minY);
        const viewW = canvas.clientWidth - pad*2;
        const viewH = canvas.clientHeight - pad*2;
        const scale = Math.min(viewW / w, viewH / h);

        // stroke path 
        ctx.lineWidth = 2;
        for (let i = 1; i < pts.length; i++) {
          const a = pts[i-1], b = pts[i];
          const ax = pad + (a.x - minX) * scale;
          const ay = pad + (a.y - minY) * scale;
          const bx = pad + (b.x - minX) * scale;
          const by = pad + (b.y - minY) * scale;
          const dt = Math.max(1, (b.t - a.t));
          const dist = Math.hypot(bx-ax, by-ay);
          const speed = dist / Math.max(1, dt/1000); 
          const t = Math.min(1, speed / 2000); 
          const r = Math.floor(45 + 210 * t);
          const g = Math.floor(212 - 120 * t);
          const bl = Math.floor(191 - 120 * t);
          ctx.strokeStyle = `rgb(${r},${g},${bl})`;
          ctx.beginPath();
          ctx.moveTo(ax, ay);
          ctx.lineTo(bx, by);
          ctx.stroke();
        }

        // draw points
        for (let p of pts) {
          const x = pad + (p.x - minX) * scale;
          const y = pad + (p.y - minY) * scale;
          ctx.beginPath();
          ctx.fillStyle = p.press ? "rgba(255,180,120,0.95)" : "rgba(200,220,255,0.9)";
          ctx.arc(x,y,3,0,Math.PI*2);
          ctx.fill();
        }
      }

      setTimeout(()=>{ if (mounted) tick(); }, 200);
    };

    const onResize = () => { resize(); };
    window.addEventListener("resize", onResize);
    tick();

    return () => { mounted = false; drawRef.current.mounted = false; window.removeEventListener("resize", onResize); };
  }, [events, propPoints, canvasHeight]);

  // send collected events to backend
  async function sendToServer() {
    const payloadEvents = propPoints && Array.isArray(propPoints) ? propPoints : events;
    if (!payloadEvents || !payloadEvents.length) { alert("No events to send"); return; }
    try {
      await collectMouse({ session_id: sessionId, events: payloadEvents, meta: { source: "visualizer" }, predict: true });
      alert("Sent to server (predict=true)");
    } catch (e) {
      alert("Send failed: "+(e?.body?.error || e.message || JSON.stringify(e)));
    }
  }

  // small UI: Session id, send button, stats
  return (
    <div style={{marginTop:8}}>
      <div style={{display:"flex",gap:10,alignItems:"center",flexWrap:"wrap"}}>
        <label style={{color:"#cbd5e1",fontSize:13}}>Session id</label>
        <input
          value={sessionId}
          onChange={e=>setSessionId(e.target.value)}
          style={{padding:"6px 8px",borderRadius:6, border:"1px solid rgba(255,255,255,0.06)", background:"rgba(255,255,255,0.02)", color:"inherit"}}
        />
        <button className="btn primary" onClick={sendToServer} style={{marginLeft:6}}>Send to backend (predict)</button>
      </div>

      <canvas
        ref={canvasRef}
        style={{ width: "100%", height: canvasHeight, marginTop: 12, borderRadius: 8, display: "block", border: "1px solid rgba(255,255,255,0.03)" }}
      />

      <div style={{marginTop:12, color:"#cbd5e1"}}>
        <strong style={{display:"block",marginBottom:6}}>Stats:</strong>
        <div>Events collected: {stats.event_count || 0}</div>
        <div>Avg speed: {stats.avg_speed ? stats.avg_speed.toFixed(2) : "-"}</div>
        <div>Avg acceleration: {stats.avg_acc ? stats.avg_acc.toFixed(2) : "-"}</div>
        <div>Curvature: {stats.curvature ? stats.curvature.toFixed(4) : "-"}</div>
        <div>Clicks: {stats.clicks || 0}</div>
        <div>Avg dt (s): {stats.avg_dt ? stats.avg_dt.toFixed(3) : "-"}</div>
      </div>
    </div>
  );
}