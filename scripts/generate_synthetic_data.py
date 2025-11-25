# scripts/generate_synthetic_data.py
"""
Generate synthetic mouse movement sessions: human, basic bots, and advanced bots.
Outputs: data/raw/mouse_synthetic.csv
"""
import os
import csv
import math
import random
import numpy as np
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / "mouse_synthetic.csv"
N_HUMANS = 300
N_BASIC_BOTS = 200
N_ADV_BOTS = 200


def gen_human(length=200):
    """Generate human-like traces with realistic jitter and pauses."""
    x, y = np.random.randint(100, 800), np.random.randint(100, 800)
    t = 0
    samples = []
    angle = np.random.uniform(0, 2 * math.pi)
    speed = np.random.uniform(1, 4)

    for i in range(length):
        angle += np.random.normal(0, 0.08)
        speed = max(0.5, speed + np.random.normal(0, 0.2))
        dx = math.cos(angle) * speed + np.random.normal(0, 1.5)
        dy = math.sin(angle) * speed + np.random.normal(0, 1.5)
        x += dx
        y += dy
        if random.random() < 0.015:
            dt = np.random.randint(100, 600)
        elif random.random() < 0.05:
            dt = np.random.randint(40, 120)
        else:
            dt = np.random.randint(10, 25)

        t += dt

        # add jitter to mimic hand tremor and measurement noise
        jitter_x = np.random.normal(0, 2)
        jitter_y = np.random.normal(0, 2)
        jitter_t = np.random.normal(0, 5)

        samples.append((x + jitter_x, y + jitter_y, max(0, t + jitter_t)))
    return samples


def gen_basic_bot(length=200):
    """Generate basic, rigid bot-like movement (straight lines, constant speed)."""
    x, y = np.random.randint(100, 800), np.random.randint(100, 800)
    t = 0
    samples = []

    dir_angle = np.random.uniform(0, 2 * math.pi)
    step_size = np.random.uniform(3, 6)

    for i in range(length):
        dx = math.cos(dir_angle) * step_size
        dy = math.sin(dir_angle) * step_size
        x += dx
        y += dy
        t += 10  

        # minimal jitter to simulate sensor precision
        x_j = x + np.random.normal(0, 0.4)
        y_j = y + np.random.normal(0, 0.4)
        t_j = t + np.random.normal(0, 1.0)

        samples.append((x_j, y_j, max(0, t_j)))
    return samples


def gen_adv_bot(length=200):
    """Generate advanced bot-like movement (non-linear, smooth, with noise)."""
    x, y = np.random.randint(100, 800), np.random.randint(100, 800)
    t = 0
    samples = []
    n_ctrl = np.random.randint(3, 6)
    ctrl_points = np.cumsum(np.random.randn(n_ctrl, 2) * np.random.uniform(50, 150), axis=0) + np.array([x, y])

    def bezier(p0, p1, p2, t):
        return (1-t)**2 * p0 + 2*(1-t)*t*p1 + t**2*p2

    for i in range(length):
        seg = i / length * (n_ctrl - 2)
        idx = int(seg)
        local_t = seg - idx
        if idx >= len(ctrl_points) - 2:
            idx = len(ctrl_points) - 3
            local_t = 1.0
        p0, p1, p2 = ctrl_points[idx:idx+3]
        bx, by = bezier(p0[0], p1[0], p2[0], local_t), bezier(p0[1], p1[1], p2[1], local_t)

        # add realistic jitter — less than humans but not zero
        bx += np.random.normal(0, 1.0)
        by += np.random.normal(0, 1.0)
        t += np.random.randint(8, 20)

        samples.append((bx, by, t))
    return samples

def main():
    rows = []

    print("Generating synthetic sessions...")
    for i in range(N_HUMANS):
        sid = f"human_{i:04d}"
        seq = gen_human(length=np.random.randint(150, 300))
        rows.append((sid, seq, 1))

    for i in range(N_BASIC_BOTS):
        sid = f"bot_basic_{i:04d}"
        seq = gen_basic_bot(length=np.random.randint(150, 300))
        rows.append((sid, seq, 0))

    for i in range(N_ADV_BOTS):
        sid = f"bot_adv_{i:04d}"
        seq = gen_adv_bot(length=np.random.randint(150, 300))
        rows.append((sid, seq, 0))

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", newline="", encoding="utf8") as f:
        w = csv.writer(f)
        w.writerow(["session_id", "x", "y", "t", "label"])
        for sid, seq, label in rows:
            for x, y, t in seq:
                w.writerow([sid, x, y, t, label])

    print(f"✅ Generated {len(rows)} sessions → {OUT_FILE}")


if __name__ == "__main__":
    main()