# scripts/feature_extraction.py
import numpy as np, math

def seq_to_features(xs, ys, ts):
    xs = np.array(xs, dtype=float)
    ys = np.array(ys, dtype=float)
    ts = np.array(ts, dtype=float)
    if len(xs) < 3:
        return [0.0]*20
    dx = np.diff(xs); dy = np.diff(ys); dt = np.diff(ts); dt = np.where(dt==0,1.0,dt)
    vx = dx/dt; vy = dy/dt; speed = np.sqrt(vx*vx + vy*vy)
    acc = np.diff(speed)
    if acc.size==0: acc = np.array([0.0])
    angles=[]
    for i in range(1, len(dx)):
        a1 = math.atan2(dy[i-1], dx[i-1]); a2 = math.atan2(dy[i], dx[i])
        da = a2-a1
        while da<=-math.pi: da += 2*math.pi
        while da>math.pi: da -= 2*math.pi
        angles.append(da)
    angles=np.array(angles) if len(angles)>0 else np.array([0.0])
    pause_thresh = np.percentile(dt, 75) * 1.5
    pause_frac = float((dt > pause_thresh).sum()) / max(1, len(dt))
    width = xs.max()-xs.min(); height = ys.max()-ys.min()
    bbox_aspect = float(width/height) if height!=0 else 0.0
    path_len = float(np.sum(np.sqrt(dx*dx + dy*dy)))
    feats = [
        float(np.mean(speed)), float(np.std(speed)), float(np.max(speed)),
        float(np.mean(acc)), float(np.std(acc)), float(np.max(acc)),
        float(np.mean(np.abs(dx))), float(np.std(dx)),
        float(np.mean(np.abs(dy))), float(np.std(dy)),
        float(np.mean(angles)), float(np.std(angles)),
        float(pause_frac),
        float(bbox_aspect),
        float(path_len),
        float(np.percentile(speed, 25)),
        float(np.percentile(speed, 50)),
        float(np.percentile(speed, 75)),
        float(np.median(dt)),
        float(len(xs))
    ]
    return feats
