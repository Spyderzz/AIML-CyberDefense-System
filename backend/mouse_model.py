# backend/mouse_model.py
import os
import json
import math
import joblib
import numpy as np
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def _to_arrays(events):
    if len(events) == 0:
        return None, None, None

    xs, ys, ts = [], [], []

    for e in events:
        if isinstance(e, dict):
            x = e.get("x"); y = e.get("y"); t = e.get("t")
        else:
            try:
                x, y, t = e[0], e[1], e[2]
            except Exception:
                x, y, t = None, None, None

        if x is None or y is None or t is None:
            continue

        xs.append(float(x)); ys.append(float(y)); ts.append(float(t))

    if len(xs) == 0:
        return None, None, None

    xs = np.array(xs, dtype=float)
    ys = np.array(ys, dtype=float)
    ts = np.array(ts, dtype=float)

    # Fix non-monotonic timestamps
    try:
        if (np.diff(ts) < 0).any():
            ts = np.cumsum(np.clip(np.diff(ts, prepend=ts[0]), 1.0, None))
    except Exception:
        pass

    try:
        if ts.size and ts.max() > 1e11:
            # timestamps are very large (ms since epoch) — convert to seconds
            ts = ts / 1000.0
            logger.debug("mouse_model: detected epoch-ms timestamps, converted to seconds")
    except Exception:
        
        pass
    return xs, ys, ts


def extract_features_from_events(events: List[Dict[str, Any]]):
    xs, ys, ts = _to_arrays(events)
    if xs is None or len(xs) < 3:

        return [0.0] * 20

    dx = np.diff(xs)
    dy = np.diff(ys)
    dt = np.diff(ts)

    dt = np.where(dt == 0, 1.0, dt)

    vx = dx / dt
    vy = dy / dt
    speed = np.sqrt(vx ** 2 + vy ** 2)

    acc = np.diff(speed)
    if acc.size == 0:
        acc = np.array([0.0])

    angles = []
    for i in range(1, len(dx)):
        x1, y1 = dx[i - 1], dy[i - 1]
        x2, y2 = dx[i], dy[i]
        a1, a2 = math.atan2(y1, x1), math.atan2(y2, x2)
        da = a2 - a1
        while da <= -math.pi:
            da += 2 * math.pi
        while da > math.pi:
            da -= 2 * math.pi
        angles.append(da)

    angles = np.array(angles) if len(angles) else np.array([0.0])

    pause_thresh = np.percentile(dt, 75) * 1.5
    pause_frac = float((dt > pause_thresh).sum()) / max(1, len(dt))

    width = xs.max() - xs.min() if xs.size else 0.0
    height = ys.max() - ys.min() if ys.size else 0.0
    bbox_aspect = float(width / height) if height != 0 else 0.0

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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "processed"))

def _safe_load_json(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

selected_feat_path = os.path.join(MODEL_DIR, "mouse_selected_features.json")
selected_features = _safe_load_json(selected_feat_path, {}).get("selected_features", None)

if selected_features is None:
    selected_indices = list(range(20))
else:
    feature_names = [
        "mean_speed", "std_speed", "max_speed",
        "mean_acc", "std_acc", "max_acc",
        "mean_abs_dx", "std_dx",
        "mean_abs_dy", "std_dy",
        "mean_angles", "std_angles",
        "pause_frac",
        "bbox_aspect",
        "path_len",
        "speed_p25", "speed_p50", "speed_p75",
        "median_dt",
        "n_events"
    ]
    try:
        selected_indices = [feature_names.index(f) for f in selected_features]
    except Exception:
        logger.warning("mouse_model: selected_features mapping failed, falling back to full set")
        selected_indices = list(range(20))


rf_model = None
rf_scaler = None

try:
    rf_model = joblib.load(os.path.join(MODEL_DIR, "mouse_rf.save"))
    logger.info("Loaded RF model")
except Exception:
    rf_model = None
    logger.warning("mouse_model: could not load RF model")

try:
    rf_scaler = joblib.load(os.path.join(MODEL_DIR, "mouse_scaler.save"))
    logger.info("Loaded RF scaler")
except Exception:
    rf_scaler = None
    logger.warning("mouse_model: could not load RF scaler")

lstm_model = None
lstm_scaler = None
lstm_meta = None

env_lstm_path = os.environ.get("MOUSE_LSTM_PATH", "").strip()

candidates = []
if env_lstm_path:
    candidates.append(env_lstm_path)
candidates.append(os.path.join(MODEL_DIR, "mouse_lstm.keras"))
candidates.append(os.path.join(MODEL_DIR, "mouse_lstm.h5"))
candidates.append(os.path.join(MODEL_DIR, "mouse_lstm.keras.zip"))

for p in candidates:
    try:
        if not p:
            continue
        if not os.path.exists(p):
            continue
        from tensorflow.keras.models import load_model # type: ignore
        lstm_model = load_model(p)
        logger.info("Loaded LSTM model from %s", p)
        break
    except Exception as e:
        lstm_model = None
        logger.debug("mouse_model: failed loading LSTM from %s (%s)", p, e)

try:
    lstm_scaler = joblib.load(os.path.join(MODEL_DIR, "mouse_lstm_scaler.save"))
    logger.info("Loaded LSTM scaler")
except Exception:
    lstm_scaler = None
    logger.warning("mouse_model: could not load LSTM scaler")

lstm_meta = _safe_load_json(os.path.join(MODEL_DIR, "mouse_lstm_meta.json"), {})


# Load Ensemble Meta
ensemble_meta = _safe_load_json(
    os.path.join(MODEL_DIR, "mouse_ensemble_meta.json"),
    {"rf_weight": 0.5, "lstm_weight": 0.5}
)

w_rf = float(ensemble_meta.get("rf_weight", 0.5))
w_lstm = float(ensemble_meta.get("lstm_weight", 0.5))

#  Unified Prediction API (RF + LSTM + Ensemble)
def predict_mouse_features(features_20):

    try:
        feats = np.array(features_20, dtype=float)[selected_indices]
    except Exception:
        feats = np.zeros(len(selected_indices), dtype=float)

    feats = feats.reshape(1, -1)

    rf_prob = None
    if rf_model is not None:
        try:
            xf = rf_scaler.transform(feats) if rf_scaler else feats
            rf_prob = float(rf_model.predict_proba(xf)[0][1])
        except Exception:
            rf_prob = None

    lstm_prob = None
    if lstm_model is not None and lstm_scaler is not None and lstm_meta:
        try:
            seq_len = int(lstm_meta.get("seq_len", 8))
            feat_dim = feats.shape[1]

            pad = np.zeros((max(0, seq_len - 1), feat_dim), dtype=float)
            seq = np.vstack([feats, pad])[:seq_len]

            seq_s = lstm_scaler.transform(seq).reshape(1, seq_len, feat_dim)
            lstm_prob = float(lstm_model.predict(seq_s, verbose=0).ravel()[0])
        except Exception:
            lstm_prob = None

    if rf_prob is None and lstm_prob is None:
        ensemble_prob = 0.0
    elif lstm_prob is None:
        ensemble_prob = rf_prob
    elif rf_prob is None:
        ensemble_prob = lstm_prob
    else:
        total_w = (w_rf + w_lstm) if (w_rf + w_lstm) != 0 else 1.0
        ensemble_prob = (w_rf * rf_prob + w_lstm * lstm_prob) / total_w

    return {
        "rf_prob": rf_prob,
        "lstm_prob": lstm_prob,
        "ensemble_prob": ensemble_prob
    }

def predict_from_events(events: List[Dict[str, Any]]) -> Dict[str, Any]:

    try:
        feats20 = extract_features_from_events(events)
    except Exception as e:
        logger.exception("predict_from_events: feature extraction failed: %s", e)
        feats20 = [0.0] * 20

    try:
        model_probs = predict_mouse_features(feats20)
    except Exception as e:
        logger.exception("predict_from_events: model prediction failed: %s", e)
        model_probs = {"rf_prob": None, "lstm_prob": None, "ensemble_prob": None}

    bot_prob = model_probs.get("ensemble_prob")
    if bot_prob is None:
        if model_probs.get("rf_prob") is not None:
            bot_prob = model_probs.get("rf_prob")
        elif model_probs.get("lstm_prob") is not None:
            bot_prob = model_probs.get("lstm_prob")
        else:
            bot_prob = 0.0

    try:
        bot_prob = float(bot_prob)
    except Exception:
        bot_prob = 0.0
    bot_prob = max(0.0, min(1.0, bot_prob))
    human_prob = 1.0 - bot_prob

    label = "bot" if bot_prob >= 0.5 else "human"

    # build response
    resp = {
        "label": label,
        "bot_prob": bot_prob,
        "human_prob": human_prob,
        "confidence": bot_prob,
        "models": {
            "rf_prob": model_probs.get("rf_prob"),
            "lstm_prob": model_probs.get("lstm_prob"),
            "ensemble_prob": model_probs.get("ensemble_prob")
        },
        "features": feats20
    }

    return resp


# module exports 
__all__ = [
    "extract_features_from_events",
    "predict_mouse_features",
    "predict_from_events",
]