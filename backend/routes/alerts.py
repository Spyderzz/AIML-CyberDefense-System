# backend/routes/alerts.py
from flask import Blueprint, jsonify, request, current_app
from datetime import datetime
import threading
from typing import List, Dict, Any, Optional

alerts_bp = Blueprint("alerts", __name__)
collect_bp = None
_module_alert_store: List[Dict[str, Any]] = []
_module_store_lock = threading.Lock()

def init_app(app):
    app.extensions.setdefault("alerts_store", [])
    return app

def _get_store():
    try:
        # If inside an application context, use per-app store
        store = current_app.extensions.setdefault("alerts_store", [])
        return store
    except RuntimeError:
        return _module_alert_store

def _append_alert_to_store(alert: Dict[str, Any]):
    try:
        
        store = current_app.extensions.setdefault("alerts_store", [])
        store.append(alert)
        return alert
    except RuntimeError:
        
        with _module_store_lock:
            _module_alert_store.append(alert)
            return alert

@alerts_bp.route("/api/alerts", methods=["GET"])
@alerts_bp.route("/alerts", methods=["GET"])
def get_alerts():
    store = _get_store()

    limit = request.args.get("limit", default=50, type=int)
    since = request.args.get("since", default=None, type=str)

    filtered = list(store) 

    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            # keep alerts with timestamp >= since_dt
            def _parse_ts(a):
                try:
                    return datetime.fromisoformat(a.get("timestamp"))
                except Exception:
                    return None
            filtered = [a for a in filtered if (_parse_ts(a) is not None and _parse_ts(a) >= since_dt)]
        except Exception:
            
            pass

    
    result = list(reversed(filtered))[:limit]
    return jsonify(result), 200

@alerts_bp.route("/api/alerts", methods=["POST"])
@alerts_bp.route("/alerts", methods=["POST"])
def post_alert():
    j = request.get_json(force=True, silent=True) or {}
    severity = j.get("severity", "info")
    message = j.get("message", "alert")
    meta = j.get("meta", {}) or {}

    alert = {
        "id": None, 
        "timestamp": datetime.utcnow().isoformat(),
        "severity": severity,
        "message": message,
        "meta": meta
    }
    store = _get_store()
    if store is _module_alert_store:
        with _module_store_lock:
            store.append(alert)
            alert["id"] = str(len(store))
    else:
        store.append(alert)
        alert["id"] = str(len(store))

    return jsonify(alert), 201


def add_alert(severity: str = "info", message: str = "test alert", meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    store = _get_store()
    a = {
        "id": None,
        "timestamp": datetime.utcnow().isoformat(),
        "severity": severity,
        "message": message,
        "meta": meta or {}
    }

    if store is _module_alert_store:
        with _module_store_lock:
            _module_alert_store.append(a)
            a["id"] = str(len(_module_alert_store))
    else:
        store.append(a)
        a["id"] = str(len(store))
    return a