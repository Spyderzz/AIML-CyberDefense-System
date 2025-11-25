// frontend/src/pages/Index.jsx
import React from "react";
import Topbar from "../components/Topbar";

export default function Index() {
  return (
    <div className="page-root">
      <Topbar />

      <section className="hero container">
        <div className="hero-inner">
          <div className="badge">⚡ Real-time AI-Powered Security</div>
          <h1 className="hero-title">
            Advanced Cybersecurity with <span className="hero-accent">Machine Learning</span>
          </h1>
          <p className="hero-sub">
            Detect threats in real-time with AI-powered mouse behavior analysis, network flow monitoring,
            and intelligent alert systems.
          </p>

          <div className="hero-ctas">
            <button className="btn primary" onClick={()=> window.location.href="/register"}>Start Free Trial →</button>
            <button className="btn outline" onClick={()=> window.location.href="/dashboard"}>View Dashboard</button>
          </div>
        </div>
      </section>

      <section className="features container">
        <div className="feature-card">
          <div className="feature-icon lock">🔒</div>
          <h3>Bot Detection</h3>
          <p>ML-powered mouse behavior analysis to distinguish human users from bots in real-time.</p>
        </div>

        <div className="feature-card">
          <div className="feature-icon graph">📈</div>
          <h3>Network Monitoring</h3>
          <p>Live traffic analysis with intelligent DDoS Detection and anomaly alerts.</p>
        </div>

        <div className="feature-card">
          <div className="feature-icon alert">⚠️</div>
          <h3>Real-time Alerts</h3>
          <p>Instant notifications for suspicious activities with detailed threat analysis.</p>
        </div>
      </section>
    </div>
  );
}