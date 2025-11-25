# backend/routes/collect.py

from flask import Blueprint, request, jsonify, current_app
from werkzeug.exceptions import BadRequest
import time
import traceback
import json
import os
from typing import Any, Tuple

bp = Blueprint("collect", __name__, url_prefix="/api")

_MOUSE_EVENTS_STORE = []  # each entry: {ts, session_id, events, meta}

MODEL = None
try:
    from .. import mouse_model as mm  # type: ignore
    MODEL = mm
except Exception:
    try:
        import mouse_model as mm  # type: ignore
        MODEL = mm
    except Exception:
        MODEL = None

_PREDICT_FN_NAMES = [
    "predict", "predict_mouse", "predict_from_events", "predict_events",
    "infer", "inference", "_predict_mouse_from_events"
]

def _get_model_predict_fn():
    """Return a callable that accepts events and returns model output."""
    if not MODEL:
        return None
    for name in _PREDICT_FN_NAMES:
        fn = getattr(MODEL, name, None)
        if callable(fn):
            return fn
    # Some modules expose a Model class with .predict
    ModelClass = getattr(MODEL, "Model", None) or getattr(MODEL, "MouseModel", None)
    if ModelClass and callable(ModelClass):
        try:
            inst = ModelClass()
            if hasattr(inst, "predict") and callable(inst.predict):
                return inst.predict
        except Exception:
            pass
    return None


_predict_fn_cached = None

def _resolve_predict_fn():
    global _predict_fn_cached
    if _predict_fn_cached is not None:
        return _predict_fn_cached
    _predict_fn_cached = _get_model_predict_fn()
    return _predict_fn_cached


def _norm_prob(v):
    try:
        if v is None:
            return None
        v = float(v)
        if v > 1.0:
            
            return max(0.0, min(1.0, v / 100.0))
        return max(0.0, min(1.0, v))
    except Exception:
        return None

def _normalize_model_output(out: Any) -> dict:
    result = {
        "label": None,
        "prediction": None,
        "bot_prob": None,
        "human_prob": None,
        "confidence": None,
        "confidence_is": None,
        "raw": out
    }

    try:
        
        if isinstance(out, dict):
            
            label = out.get("label") or out.get("prediction") or out.get("pred") or out.get("class") or out.get("result")
            bp = out.get("bot_prob") if "bot_prob" in out else None
            hp = out.get("human_prob") if "human_prob" in out else None
            conf = out.get("confidence") if "confidence" in out else (out.get("score") if "score" in out else out.get("prob") if "prob" in out else out.get("probability") if "probability" in out else None)
            bp_n = _norm_prob(bp) if bp is not None else None
            hp_n = _norm_prob(hp) if hp is not None else None
            conf_n = _norm_prob(conf) if conf is not None else None

            if bp_n is not None:
                bot_prob = bp_n
                human_prob = 1.0 - bot_prob
                confidence = bot_prob
                confidence_is = "bot_prob"
            elif hp_n is not None:
                human_prob = hp_n
                bot_prob = 1.0 - human_prob
                confidence = bot_prob
                confidence_is = "bot_prob"
            elif conf_n is not None:
               
                bot_prob = conf_n
                human_prob = 1.0 - bot_prob
                confidence = bot_prob
                confidence_is = "bot_prob"
                
                if label and str(label).lower() in ("human", "0", "false") and conf_n > 0.5:
                    
                    bot_prob = 1.0 - conf_n
                    human_prob = conf_n
                    confidence = bot_prob
                    confidence_is = "bot_prob"
            else:
                bot_prob = None; human_prob = None; confidence = None; confidence_is = None

            
            result["label"] = str(label) if label is not None else None
            result["prediction"] = result["label"]
            result["bot_prob"] = bot_prob
            result["human_prob"] = human_prob
            result["confidence"] = confidence
            result["confidence_is"] = confidence_is
            return result

        if isinstance(out, (list, tuple)) and len(out) >= 1:
            label = out[0]
            score = out[1] if len(out) > 1 else None
            s_n = _norm_prob(score) if score is not None else None
            result["label"] = str(label) if label is not None else None
            result["prediction"] = result["label"]
            if s_n is not None:
                
                if result["label"] and str(result["label"]).lower() in ("human", "0", "false") and s_n > 0.5:
                    bot_prob = 1.0 - s_n
                else:
                    bot_prob = s_n
                result["bot_prob"] = bot_prob
                result["human_prob"] = 1.0 - bot_prob
                result["confidence"] = result["bot_prob"]
                result["confidence_is"] = "bot_prob"
            return result

        # scalar numeric -> treat as bot_prob
        if isinstance(out, (int, float)):
            bp = _norm_prob(out)
            result["bot_prob"] = bp
            result["human_prob"] = 1.0 - bp if bp is not None else None
            result["confidence"] = bp
            result["confidence_is"] = "bot_prob"
            result["label"] = "bot" if (bp is not None and bp >= 0.5) else "human"
            result["prediction"] = result["label"]
            return result

        result["label"] = str(out)
        result["prediction"] = result["label"]
        return result

    except Exception:
        current_app.logger.exception("normalize_model_output failed")
        result["raw"] = out
        return result

def _safe_predict(events) -> Tuple[bool, Any]:
    fn = _resolve_predict_fn()
    if not fn:
        return False, "no_model"
    try:
        out = fn(events)
        if out is None:
            return False, "no_output"
        
        normalized = _normalize_model_output(out)
        if normalized.get("confidence") is None and normalized.get("bot_prob") is not None:
            normalized["confidence"] = normalized["bot_prob"]
            normalized["confidence_is"] = "bot_prob"
        return True, normalized
    except Exception as e:
        current_app.logger.exception("Model prediction error: %s", e)
        return False, {"error": str(e), "trace": traceback.format_exc()}

@bp.route("/collect_mouse", methods=["POST"])
def collect_mouse():
    try:
        payload = request.get_json(force=True)
    except BadRequest:
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    if not payload:
        return jsonify({"ok": False, "error": "empty_payload"}), 400

    session_id = payload.get("session_id") or payload.get("sid") or None
    events = payload.get("events") or payload.get("data") or []
    meta = payload.get("meta") or {}
    predict_flag = bool(payload.get("predict", False))

    if not isinstance(events, list):
        return jsonify({"ok": False, "error": "events_must_be_list"}), 400

    entry = {
        "ts": int(time.time()),
        "session_id": session_id,
        "events_count": len(events),
        "events": events,
        "meta": meta,
    }
    try:
        _MOUSE_EVENTS_STORE.append(entry)
    except Exception:
        current_app.logger.exception("Failed to append event")

    resp = {"ok": True, "saved": True, "session_id": session_id, "events_count": len(events)}


    if predict_flag and len(events) > 0:
        ok, pred = _safe_predict(events)
        if ok:
            prediction = {
                "label": pred.get("label"),
                "prediction": pred.get("prediction"),
                "bot_prob": pred.get("bot_prob"),
                "human_prob": pred.get("human_prob"),
                "confidence": pred.get("confidence"),
                "confidence_is": pred.get("confidence_is"),
                "raw": pred.get("raw")
            }
            resp["prediction"] = prediction

            # socketio emit
            try:
                socketio = current_app.extensions.get("socketio")
                if socketio:
                    # emit mouse_prediction for dashboard
                    try:
                        socketio.emit("mouse_prediction", {"session_id": session_id, "prediction": prediction}, broadcast=True)
                    except Exception:
                        current_app.logger.exception("socketio.emit(mouse_prediction) failed")
                    # Determine high-alert using environment threshold
                    try:
                        threshold_env = os.environ.get("ALERT_THRESHOLD") or os.environ.get("BLOCK_THRESHOLD") or os.environ.get("ALERT_THRESHOLD", None)
                        threshold = float(threshold_env) if threshold_env is not None else 0.9
                    except Exception:
                        threshold = 0.9
                    is_high = False
                    try:
                        # consider bot_prob if present, else confidence
                        val = prediction.get("bot_prob")
                        if val is None:
                            val = prediction.get("confidence")
                        if isinstance(val, (int, float)) and val >= threshold:
                            is_high = True
                        
                        lab = str(prediction.get("label") or "").lower()
                        if "bot" in lab or "attack" in lab:
                            is_high = True
                    except Exception:
                        is_high = False

                    if is_high:
                        alert_payload = {
                            "meta": meta or {},
                            "prob": prediction.get("bot_prob") or prediction.get("confidence") or 1.0,
                            "label": prediction.get("label"),
                            "session_id": session_id,
                            "events_count": len(events),
                        }
                        try:
                            socketio.emit("new_alert", alert_payload, broadcast=True)
                        except Exception:
                            current_app.logger.exception("socketio.emit(new_alert) failed")
            except Exception:
                current_app.logger.exception("Socket emit failed in collect_mouse")
        else:
            
            resp["prediction_error"] = pred

    return jsonify(resp)