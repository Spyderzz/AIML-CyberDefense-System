import React, { useState, useEffect } from "react";
import Topbar from "../components/Topbar";
import MouseVisualizer from "../components/MouseVisualizer";
import { useMouseDynamics } from "../hooks/useMouseDynamics";
import { collectMouse } from "../services/api";
import { connectSocket } from "../services/socket";
import { toast } from "../utils/toast";

export default function MouseTest(){
  const [points, setPoints] = useState([]);
  const [running, setRunning] = useState(false);

  useEffect(()=> {
    const socket = connectSocket(null, (data)=>{
      if (data && data.points) setPoints(data.points);
    });
    return ()=> socket && socket.disconnect();
  }, []);

  const onBatch = async (payload) => {
    // payload: { session_id, events, features, clicks }
    setPoints(payload.events.slice(-120));
    try {
      await collectMouse(payload);
    } catch(e){ console.warn("collectMouse failed", e); }
  };

  const m = useMouseDynamics(onBatch);

  function toggle() {
    if (!running) { m.start(); setRunning(true); toast("Mouse tracking started", "success") }
    else { m.stop(); setRunning(false); toast("Mouse tracking stopped", "info") }
  }

  return (
    <div>
      <Topbar />
      <div className="container" style={{paddingTop:40}}>
        <h2>Mouse Tracker — live</h2>
        <p className="muted">Start mouse tracking to stream dynamics to the server.</p>
        <div style={{marginTop:18}}>
          <button className="btn primary" onClick={toggle}>{running ? "Stop Tracking" : "Start Tracking"}</button>
          <div style={{marginTop:18}}>
            <MouseVisualizer points={points} width={900} height={260} />
          </div>
        </div>
      </div>
    </div>
  );
}
