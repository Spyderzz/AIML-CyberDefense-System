// frontend/src/utils/mouseFeatures.js

export function computeMouseFeatures(events) {
  if (!events || events.length < 2) {
    return {
      count: events ? events.length : 0,
      avg_velocity: 0,
      median_velocity: 0,
      max_velocity: 0,
      avg_acc: 0,
      max_acc: 0,
      std_acc: 0,
      curvature_std: 0,
      curvature_mean: 0,
      pause_count: 0,
      longest_pause: 0,
      pct_pause_time: 0,
      tortuosity: 0,
      smoothness_index: 0,
      mean_angle: 0,
      angle_std: 0,
      click_count: 0,
      avg_dwell_before_click: 0,
      avg_time_between_clicks: 0,
      click_speed: 0
    };
  }

  const diff = (a, b) => a - b;
  const mean = arr => arr.length ? arr.reduce((s,x)=>s+x,0)/arr.length : 0;
  const variance = arr => {
    if (!arr.length) return 0;
    const m = mean(arr);
    return arr.reduce((s,x)=>s + (x - m)*(x - m), 0) / arr.length;
  };
  const std = arr => Math.sqrt(variance(arr));
  const median = arr => {
    if (!arr.length) return 0;
    const s = [...arr].sort((a,b)=>a-b);
    const mid = Math.floor(s.length/2);
    return (s.length % 2) ? s[mid] : (s[mid-1]+s[mid]) / 2;
  };

  // compute instantaneous deltas, velocity, angle
  const velocities = []; // pixels / sec
  const accs = [];       // pixels / sec^2
  const dt_arr = [];
  const angles = [];     // radians
  const angle_diffs = [];
  const speeds_before_clicks = [];
  const dwell_before_clicks = [];
  const click_ts = [];

  let path_length = 0;
  const first = events[0];
  let prev = first;
  let lastAngle = null;

  const PAUSE_THRESHOLD_MS = 200;
  let pause_count = 0;
  let pause_time_sum = 0;
  let longest_pause = 0;

  for (let i = 1; i < events.length; i++) {
    const e = events[i];
    const dx = (e.x - prev.x);
    const dy = (e.y - prev.y);
    let dt_ms = (e.t - prev.t);
    if (!dt_ms || dt_ms <= 0) dt_ms = 1; // avoid zero
    const dt = dt_ms / 1000; // seconds
    const dist = Math.sqrt(dx*dx + dy*dy);
    const v = dist / dt; // px/sec
    velocities.push(v);
    dt_arr.push(dt_ms);

    path_length += dist;

    // angle
    const ang = Math.atan2(dy, dx); // [-pi,pi]
    angles.push(ang);
    if (lastAngle !== null) {
      let da = ang - lastAngle;
      while (da <= -Math.PI) da += 2*Math.PI;
      while (da > Math.PI) da -= 2*Math.PI;
      angle_diffs.push(da);
    }
    lastAngle = ang;

    // acceleration
    if (velocities.length > 1) {
      const a = (velocities[velocities.length-1] - velocities[velocities.length-2]) / dt; // px/s^2
      accs.push(a);
    }

    // pauses
    if (dt_ms > PAUSE_THRESHOLD_MS) {
      pause_count += 1;
      pause_time_sum += dt_ms;
      if (dt_ms > longest_pause) longest_pause = dt_ms;
    }

    // click dynamics
    if (e.type === "click" || e.type === "mousedown" || e.type === "mouseup") {
      click_ts.push(e.t);
      const speed_before = velocities.length ? velocities[velocities.length - 1] : 0;
      speeds_before_clicks.push(speed_before);
      const dwell = e.t - prev.t;
      dwell_before_clicks.push(dwell > 0 ? dwell : 0);
    }

    prev = e;
  }

  const avg_velocity = mean(velocities);
  const median_velocity = median(velocities);
  const max_velocity = velocities.length ? Math.max(...velocities) : 0;
  const avg_acc = mean(accs);
  const max_acc = accs.length ? Math.max(...accs) : 0;
  const std_acc = std(accs);

  // curvature proxy: use angle diffs divided by step length
  // curvature ~ |dθ| / ds ; we have dθ (angle_diffs) and per-step distances in velocities*dt.
  const curvature_samples = [];
  // We need per-step distance: rebuild from velocities and dt arrays
  // velocities[i] corresponds to step i (between event i and i+1)
  for (let i = 0; i < angle_diffs.length; i++) {
    const dtheta = Math.abs(angle_diffs[i]);
    // approximate step length using velocities[i] * dt (dt in seconds). dt_arr has ms for each step
    const step_dt = dt_arr[i+1] ? dt_arr[i+1] / 1000 : (dt_arr[i] ? dt_arr[i] / 1000 : 0.001);
    const step_speed = velocities[i] || 0;
    const ds = Math.max(0.0001, step_speed * step_dt); // pixels
    const cur = dtheta / ds; // rad per pixel
    curvature_samples.push(cur);
  }
  const curvature_std = std(curvature_samples);
  const curvature_mean = mean(curvature_samples);

  // tortuosity: path length / straight-line distance between first & last
  const total_dx = events[events.length - 1].x - events[0].x;
  const total_dy = events[events.length - 1].y - events[0].y;
  const euclidean = Math.sqrt(total_dx*total_dx + total_dy*total_dy);
  const tortuosity = euclidean > 0 ? path_length / euclidean : 1;

  // smoothness index: use inverse of normalized jerk-like measure
  // jerk proxy: std of acceleration derivatives (dA/dt)
  const jerk_samples = [];
  for (let i = 1; i < accs.length; i++) {
    const da = accs[i] - accs[i-1];
    const dt_s = dt_arr[i+1] ? dt_arr[i+1] / 1000 : 0.001;
    jerk_samples.push(Math.abs(da) / Math.max(dt_s, 0.001));
  }
  const jerk_std = std(jerk_samples);
  // smoothness index normalized: larger = smoother -> 1/(1+jerk_std)
  const smoothness_index = 1 / (1 + jerk_std);

  // angles: circular mean and circular std
  let mean_angle = 0, angle_std = 0;
  if (angles.length) {
    // compute circular mean via vector sum
    let sx = 0, sy = 0;
    for (const a of angles) { sx += Math.cos(a); sy += Math.sin(a); }
    mean_angle = Math.atan2(sy, sx);
    // circular std measure
    const R = Math.sqrt(sx*sx + sy*sy) / angles.length;
    angle_std = Math.sqrt(-2 * Math.log(R || 1e-9));
  }

  // clicks
  const click_count = click_ts.length;
  let avg_dwell_before_click = 0, avg_time_between_clicks = 0, click_speed = 0;
  if (dwell_before_clicks.length) avg_dwell_before_click = mean(dwell_before_clicks);
  if (click_ts.length > 1) {
    const diffsClicks = [];
    for (let i=1;i<click_ts.length;i++) diffsClicks.push(click_ts[i] - click_ts[i-1]);
    avg_time_between_clicks = mean(diffsClicks);
  }
  if (speeds_before_clicks.length) click_speed = mean(speeds_before_clicks);

  // pause percent of total time
  const total_time_ms = events[events.length - 1].t - events[0].t;
  const pct_pause_time = total_time_ms > 0 ? (pause_time_sum / total_time_ms) : 0;

  return {
    count: events.length,
    avg_velocity, median_velocity, max_velocity,
    avg_acc, max_acc, std_acc,
    curvature_std, curvature_mean,
    pause_count, longest_pause, pct_pause_time,
    path_length, euclidean_distance: euclidean, tortuosity, smoothness_index, jerk_std,
    mean_angle, angle_std,
    click_count, avg_dwell_before_click, avg_time_between_clicks, click_speed,
    total_time_ms
  };
}