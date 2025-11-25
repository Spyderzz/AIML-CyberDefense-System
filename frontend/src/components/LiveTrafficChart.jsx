// LiveTrafficChart.jsx
import React, { useRef, useEffect } from "react";
import {
  Chart,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  TimeScale,
  CategoryScale,
  Title,
  Legend,
  Tooltip,
  Filler,
} from "chart.js";
import { io } from "socket.io-client";

Chart.register(
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  TimeScale,
  CategoryScale,
  Title,
  Legend,
  Tooltip,
  Filler
);

export default function LiveTrafficChart({ initialData = [], height = 220 }) {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);

  const dataRef = useRef({
    labels: [],
    flows: [],
    attack: [],
    attackMeta: [],
    maxLen: 60,
  });

  useEffect(() => {
    // seed initial data if provided
    if (Array.isArray(initialData) && initialData.length > 0) {
      dataRef.current.labels = initialData.map((d) => d.time);
      dataRef.current.flows = initialData.map((d) => d.value);
      dataRef.current.attack = initialData.map(() => 0);
      dataRef.current.attackMeta = initialData.map(() => null);
    }

    if (typeof window === "undefined" || !canvasRef.current) {
      return;
    }

    const ctx = canvasRef.current.getContext && canvasRef.current.getContext("2d");
    if (!ctx) {
      console.warn("LiveTrafficChart: 2D canvas context not available.");
      return;
    }

    // gradient for flows
    const grad = ctx.createLinearGradient(0, 0, ctx.canvas.width || 600, 0);
    grad.addColorStop(0, "#06b6d4");
    grad.addColorStop(1, "#0891b2");

    const THRESHOLD = 0.9;


    try {
      chartRef.current = new Chart(ctx, {
        type: "line",
        data: {
          labels: dataRef.current.labels,
          datasets: [
            {
              label: "Active Flows",
              data: dataRef.current.flows,
              tension: 0.35,
              fill: true,
              backgroundColor: "rgba(6,182,212,0.06)",
              borderColor: grad,
              borderWidth: 2,
              pointRadius: 0,
              yAxisID: "y_flows",
              order: 1,
            },
            {
              label: "Attack Score",
              data: dataRef.current.attack,
              tension: 0.25,
              fill: false,
              borderColor: "rgba(220,38,38,0.95)",
              backgroundColor: "rgba(220,38,38,0.12)",
              borderWidth: 2,
              pointRadius: 0,
              pointHoverRadius: 4,
              yAxisID: "y_attack",
              order: 2,
            },
            {
              label: "Block Threshold",
              data: dataRef.current.labels.map(() => THRESHOLD),
              tension: 0,
              fill: false,
              borderColor: "rgba(255,165,0,0.9)",
              borderWidth: 1,
              borderDash: [6, 6],
              pointRadius: 0,
              yAxisID: "y_attack",
              order: 0,
            },
          ],
        },
        options: {
          animation: false,
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              display: true,
              position: "top",
              labels: {
                color: "rgba(255,255,255,0.85)",
                usePointStyle: true,
                padding: 12,
              },
            },
            tooltip: {
              enabled: false,
              external: function (context) {
                const tooltipModel = context.tooltip;
                if (!tooltipModel || !tooltipModel.dataPoints || tooltipModel.dataPoints.length === 0) return;
                const dp = tooltipModel.dataPoints[0];
                if (dp.datasetIndex !== 1) return;
                const idx = dp.dataIndex;
                const meta = dataRef.current.attackMeta[idx] || {};
              },
            },
          },
          scales: {
            x: { display: false },
            y_flows: {
              position: "left",
              grid: { color: "rgba(255,255,255,0.04)" },
              ticks: { color: "rgba(255,255,255,0.6)" },
              suggestedMin: 0,
            },
            y_attack: {
              position: "right",
              grid: { display: false },
              ticks: {
                color: "rgba(255,255,255,0.6)",
                min: 0,
                max: 1,
                stepSize: 0.25,
                callback: function (value) {
                  return Number(value).toFixed(2);
                },
              },
            },
          },
          elements: { line: { capBezierPoints: true } },
          onClick: function (evt) {
            try {
              const points = chartRef.current.getElementsAtEventForMode(evt, "nearest", { intersect: true }, false);
              if (!points || !points.length) return;
              const p = points[0];
              if (p.datasetIndex === 1) {
                const idx = p.index;
                const meta = dataRef.current.attackMeta[idx];
                if (meta) {
                  console.info("Attack point clicked. payload:", meta.payload || meta);
                }
              }
            } catch (e) {
            }
          },
        },
      });
    } catch (err) {
      console.error("LiveTrafficChart: Chart creation failed:", err);
      return;
    }

    function pushTick({ timeLabel, flowValue = null, attackValue = null, attackMeta = null }) {
      const D = dataRef.current;
      D.labels.push(timeLabel);
      if (flowValue !== null && flowValue !== undefined) {
        D.flows.push(flowValue);
      } else {
        const last = D.flows.length ? D.flows[D.flows.length - 1] : Math.max(1, Math.floor(20 + Math.random() * 6));
        const synthetic = Math.max(1, Math.floor(last + (Math.random() * 4 - 2)));
        D.flows.push(synthetic);
      }
      D.attack.push(attackValue !== null && attackValue !== undefined ? Number(attackValue) : 0);
      D.attackMeta.push(attackMeta || null);

      while (D.labels.length > D.maxLen) {
        D.labels.shift();
        D.flows.shift();
        D.attack.shift();
        D.attackMeta.shift();
      }

      const dsThreshold = chartRef.current.data.datasets[2];
      dsThreshold.data = D.labels.map(() => THRESHOLD);

      const attackDataset = chartRef.current.data.datasets[1];
      const radii = D.attackMeta.map((m) => (m && m.isHigh ? 4 : 0));
      const colors = D.attackMeta.map((m) => (m && m.isHigh ? "rgba(220,38,38,1)" : "rgba(220,38,38,0.6)"));

      attackDataset.pointRadius = radii;
      attackDataset.borderColor = colors;

      chartRef.current.data.labels = D.labels;
      chartRef.current.data.datasets[0].data = D.flows;
      chartRef.current.data.datasets[1].data = D.attack;
      chartRef.current.update("none");
    }

    // SOCKET.IO connection 
    const rawBase = (import.meta && import.meta.env && import.meta.env.VITE_API_BASE) || "";
    console.debug("[LiveTrafficChart] socket base config:", rawBase || "(same-origin)");

    const socketBase = rawBase ? rawBase.replace(/\/+$/, "") : undefined;
    const socket = io(socketBase, {
      path: "/socket.io",
      transports: ["websocket"],
      reconnection: true,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
    });

    socket.on("connect", () => {
      console.debug("[LiveTrafficChart] socket connected:", socket.id, "base:", socketBase || "(same-origin)");
    });

    socket.on("connect_error", (err) => {
      console.warn("[LiveTrafficChart] socket connect_error:", err && (err.message || err));
    });

    socket.on("reconnect_attempt", (n) => {
      console.debug("[LiveTrafficChart] socket reconnect_attempt:", n);
    });

    socket.on("disconnect", (reason) => {
      console.warn("[LiveTrafficChart] socket disconnected:", reason);
    });

    // handler for new_alert
    socket.on("new_alert", (payload) => {
      try {
        const t = new Date().toLocaleTimeString();

        if (!payload) {
          pushTick({ timeLabel: t, attackValue: 0, attackMeta: null });
          return;
        }

        let prob = null;
        if (typeof payload.prob === "number") prob = payload.prob;
        else if (typeof payload.prob_attack === "number") prob = payload.prob_attack;
        else if (typeof payload.p === "number") prob = payload.p;
        else if (typeof payload.score === "number") prob = payload.score;
        else if (typeof payload.confidence === "number") prob = payload.confidence;

        if (prob == null && payload.meta) {
          if (typeof payload.meta.prob === "number") prob = payload.meta.prob;
          else if (typeof payload.meta.score === "number") prob = payload.meta.score;
        }

        if (prob != null && prob > 1) prob = prob / 100.0;

        const isHigh = prob != null && prob >= THRESHOLD;

        let flowCount = null;
        if (payload.meta && typeof payload.meta.active_flows === "number") flowCount = payload.meta.active_flows;
        if (typeof payload.active_flows === "number") flowCount = payload.active_flows;
        if (typeof payload.flow_count === "number") flowCount = payload.flow_count;

        pushTick({
          timeLabel: t,
          flowValue: flowCount,
          attackValue: prob !== null ? Number(prob.toFixed(3)) : 0,
          attackMeta: { isHigh: isHigh, payload },
        });
      } catch (e) {
      }
    });

    socket.on("realtime_rate_block", (payload) => {
      try {
        const t = new Date().toLocaleTimeString();
        const prob = payload?.prob || 1.0;
        const meta = { isHigh: true, payload };
        pushTick({ timeLabel: t, flowValue: payload?.meta?.count || null, attackValue: Number(prob), attackMeta: meta });
      } catch (e) {}
    });

    // heartbeat to keep chart alive
    const hb = setInterval(() => {
      const D = dataRef.current;
      const allZero = D.attack.length === 0 || D.attack.every((v) => v === 0);
      if (D.labels.length === 0 || allZero) {
        const t = new Date().toLocaleTimeString();
        const prevFlow = D.flows.length ? D.flows[D.flows.length - 1] : Math.max(1, Math.floor(20 + Math.random() * 6));
        const syntheticFlow = Math.max(1, Math.floor(prevFlow + (Math.random() * 4 - 2)));
        pushTick({ timeLabel: t, flowValue: syntheticFlow, attackValue: 0, attackMeta: null });
      }
    }, 2000);

    window.__liveTrafficChartDump = () => {
      return {
        labels: dataRef.current.labels.slice(),
        flows: dataRef.current.flows.slice(),
        attack: dataRef.current.attack.slice(),
        attackMeta: dataRef.current.attackMeta.slice(),
      };
    };

    return () => {
      try {
        socket.off("new_alert");
        socket.off("realtime_rate_block");
        socket.off("connect");
        socket.off("connect_error");
        socket.off("disconnect");
        socket.disconnect();
      } catch (e) {}
      clearInterval(hb);
      if (chartRef.current) {
        try {
          chartRef.current.destroy();
        } catch (e) {}
        chartRef.current = null;
      }
    };
  }, [initialData]);

  return (
    <div style={{ height }} className="ltc-wrapper">
      <canvas ref={canvasRef} style={{ width: "100%", height: "100%" }} />
    </div>
  );
}