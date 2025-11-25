# backend/app.py
import os
import json
import time
import threading
import joblib
import logging
import traceback
import numpy as np
from collections import defaultdict, deque
import xgboost as xgb
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, render_template, abort
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
import requests
import time as _time

def _canonical_mouse_resp(out: dict, start_ts: float):
    try:
        bot = None
        if isinstance(out, dict):
            for k in ("bot_prob", "botP", "botProbability", "bot", "prob", "score", "confidence"):
                if out.get(k) is not None:
                    try:
                        bot = float(out.get(k))
                        break
                    except Exception:
                        bot = None
            # if human_prob is present prefer invert
            if bot is None and out.get("human_prob") is not None:
                try:
                    bot = 1.0 - float(out.get("human_prob"))
                except Exception:
                    bot = None

        if bot is None:
            label = None
            if isinstance(out, dict):
                label = (out.get("label") or out.get("prediction") or out.get("result") or "").lower()
            if isinstance(label, str) and label:
                bot = 1.0 if label.startswith("bot") else 0.0

        if bot is None:
            bot = 0.0
        try:
            bot = float(bot)
        except Exception:
            bot = 0.0
        if bot > 1.0:
            bot = bot / 100.0
        bot = max(0.0, min(1.0, bot))
        human = max(0.0, min(1.0, 1.0 - bot))

    except Exception:
        bot = 0.0
        human = 1.0

    out["bot_prob"] = float(bot)
    out["human_prob"] = float(human)
    out["_server_latency_ms"] = int((_time.time() - float(start_ts)) * 1000)
    return out


try:
    from tensorflow.keras.models import load_model as tf_load_model  # type: ignore
    from tensorflow.keras.preprocessing.sequence import pad_sequences  # type: ignore
    from tensorflow.keras.utils import custom_object_scope  # type: ignore
except Exception:
    tf_load_model = None
    pad_sequences = None
    custom_object_scope = None

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(ROOT, ".env"))


from backend.db import insert_alert, save_mouse, get_latest_alerts
from backend.auth import auth_bp, jwt, SECRET_KEY  
from backend.mouse_model import extract_features_from_events, selected_indices


APP_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')

app = Flask(__name__,
            static_folder=os.path.join(APP_DIR, 'static'),
            template_folder=os.path.join(APP_DIR, 'templates'),
            static_url_path='')

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", SECRET_KEY if 'SECRET_KEY' in globals() else "dev-secret")
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

# create limiter instance
# app.config["RATELIMIT_ENABLED"] = False
limiter = Limiter(key_func=get_remote_address, default_limits=[app.config.get("RATE_LIMIT", "200 per hour")])
limiter.init_app(app)

# CORS / SocketIO CORS
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")

# Build a list that includes both hostnames (helps when browser uses 127.0.0.1)
_allowed_origins = [FRONTEND_ORIGIN]
if "localhost" in FRONTEND_ORIGIN:
    _allowed_origins.append(FRONTEND_ORIGIN.replace("localhost", "127.0.0.1"))

CORS(
    app,
    resources={
        r"/api/*": {"origins": _allowed_origins},
        r"/socket.io/*": {"origins": _allowed_origins},
        r"/*": {"origins": _allowed_origins},
    },
    supports_credentials=True,
    expose_headers=["Content-Type", "Access-Control-Allow-Origin", "Access-Control-Allow-Credentials"]
)

# SocketIO with matching allowed origins
socketio = SocketIO(app, cors_allowed_origins=_allowed_origins)

app.extensions = getattr(app, "extensions", {})
app.extensions["socketio"] = socketio

# ----- import alerts blueprints (robust) -----
logger = logging.getLogger("ai_ml_cyberdefense")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_ml_cyberdefense")

alerts_bp = None
collect_bp = None
# Try preferred absolute import first (when running as package: python -m backend.app)
try:
    # attempt to import both; if collect_bp not present that's fine
    from backend.routes.alerts import alerts_bp as _alerts_bp, collect_bp as _collect_bp
    alerts_bp = _alerts_bp
    collect_bp = _collect_bp
    logger.info("Imported backend.routes.alerts (blueprints loaded).")
except Exception as e_abs:
    logger.debug("Could not import backend.routes.alerts: %s", e_abs)
    # fallback to top-level import (if your project layout exposes routes as top-level package)
    try:
        from routes.alerts import alerts_bp as _alerts_bp2, collect_bp as _collect_bp2
        alerts_bp = _alerts_bp2
        collect_bp = _collect_bp2
        logger.info("Imported routes.alerts (blueprints loaded).")
    except Exception as e_rel:
        # be explicit if collect_bp couldn't be imported (common)
        logger.warning("Could not import alerts blueprints from backend.routes or routes.alerts. Proceeding without them. Errors: %s ; %s", e_abs, e_rel)
        alerts_bp = None
        collect_bp = None

# make flask proxy-aware
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# register blueprints only if available
if alerts_bp:
    try:
        app.register_blueprint(alerts_bp)
        logger.info("Registered alerts_bp blueprint.")
    except Exception as e:
        logger.warning("Failed to register alerts_bp: %s", e)
if collect_bp:
    try:
        app.register_blueprint(collect_bp)
        logger.info("Registered collect_bp blueprint.")
    except Exception as e:
        logger.warning("Failed to register collect_bp: %s", e)

# logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_ml_cyberdefense")

# Helpers: robust file finding
def find_existing_file(candidates):
    for p in candidates:
        pabs = os.path.abspath(p)
        if os.path.exists(pabs):
            return pabs
    return None

def find_lstm_scaler_path():
    candidates = [
        os.path.join(DATA_DIR, "mouse_lstm_scaler.save"),
        os.path.join(DATA_DIR, "mouse_lstm_scaler.joblib"),
        os.path.join(DATA_DIR, "mouse_lstm_scaler.pkl"),
        os.path.join(os.path.dirname(__file__), "..", "data", "mouse_lstm_scaler.save"),
        os.path.join(os.path.dirname(__file__), "..", "data", "processed", "mouse_lstm_scaler.save"),
    ]
    return find_existing_file(candidates)

def find_lstm_model_path():
    # PREFER the native Keras format first (.keras) — more robust across TF versions.
    candidates = [
        os.path.join(DATA_DIR, "mouse_lstm.keras"),
        os.path.join(os.path.dirname(__file__), "..", "data", "mouse_lstm.keras"),
        os.path.join(DATA_DIR, "mouse_lstm.h5"),
        os.path.join(os.path.dirname(__file__), "..", "data", "mouse_lstm.h5"),
        os.path.join(os.path.dirname(__file__), "..", "data", "processed", "mouse_lstm.h5"),
        # also check common container mount
        "/data/mouse_lstm.keras",
        "/data/mouse_lstm.h5",
    ]
    return find_existing_file(candidates)

# -------------------------
# Load flow detection models (RF + XGB)
# -------------------------
logger.info("Loading flow-detection models...")
rf, scaler, le, xgb_model = None, None, None, None

flow_paths = {
    "rf": os.path.join(DATA_DIR, "rf_model.save"),
    "scaler": os.path.join(DATA_DIR, "scaler_used.save"),
    "le": os.path.join(DATA_DIR, "label_encoder.save"),
    "xgb": os.path.join(DATA_DIR, "xgb_model.json"),
}

try:
    if os.path.exists(flow_paths["rf"]):
        rf = joblib.load(flow_paths["rf"])
        logger.info(" - Loaded RF model")
except Exception as e:
    logger.warning(" - Failed loading RF model: %s", e)

import os, joblib
# FORCE: load the known-correct 18-feature scaler (absolute Windows path)
import os, joblib
try:
    scaler_path = os.path.join("data", "processed", "scaler_used.save")
    # repo-relative fallback if absolute not present
    if not os.path.exists(scaler_path):
        scaler_path = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "scaler_used.save")
    scaler = None
    if os.path.exists(scaler_path):
        scaler = joblib.load(scaler_path)
        logger.info("Loaded forced flow scaler from %s", scaler_path)
    else:
        logger.warning("Forced scaler not found at %s", scaler_path)
        scaler = None
except Exception as e:
    logger.exception("Failed forcing flow scaler load: %s", e)
    scaler = None

logger.info("SCALER MEAN SHAPE: %s", getattr(scaler, "mean_", None).shape if getattr(scaler, "mean_", None) is not None else "None")

logger.info("EFFECTIVE_SCALER_PATH: %s", scaler_path)

try:
    if os.path.exists(flow_paths["le"]):
        le = joblib.load(flow_paths["le"])
        logger.info(" - Loaded label encoder")
except Exception as e:
    logger.warning(" - Failed loading label encoder: %s", e)

try:
    if os.path.exists(flow_paths["xgb"]):
        xgb_model = xgb.Booster()
        xgb_model.load_model(flow_paths["xgb"])
        logger.info(" - Loaded XGBoost model")
except Exception as e:
    logger.warning(" - Failed loading XGBoost model: %s", e)

# -------------------------
# Load mouse/bot detection models (RF + optional LSTM)
# -------------------------
logger.info("Loading mouse/bot-detection models (if present)...")
mouse_rf = None
mouse_scaler = None
mouse_lstm_model = None
mouse_lstm_scaler = None
mouse_lstm_meta = None

mouse_paths = {
    "rf": os.path.join(DATA_DIR, "mouse_rf.save"),
    "scaler": os.path.join(DATA_DIR, "mouse_scaler.save"),
    "lstm": None,  # we'll detect via find_lstm_model_path()
}

# RF & scaler
try:
    if os.path.exists(os.path.join(DATA_DIR, "mouse_rf.save")):
        mouse_rf = joblib.load(os.path.join(DATA_DIR, "mouse_rf.save"))
        logger.info(" - Loaded mouse RF model")
except Exception as e:
    logger.warning(" - Failed loading mouse RF: %s", e)

try:
    if os.path.exists(os.path.join(DATA_DIR, "mouse_scaler.save")):
        mouse_scaler = joblib.load(os.path.join(DATA_DIR, "mouse_scaler.save"))
        logger.info(" - Loaded mouse scaler")
except Exception as e:
    logger.warning(" - Failed loading mouse scaler: %s", e)

# --- Robust LSTM loader using backend.keras_custom.get_custom_objects() if present ---
try:
    # import helper mapping of custom objects (placeholder implementations)
    from backend.keras_custom import get_custom_objects as _get_keras_custom_objects  # type: ignore
except Exception:
    _get_keras_custom_objects = None

# Load LSTM scaler
lstm_scaler_path = find_lstm_scaler_path()
if lstm_scaler_path:
    try:
        mouse_lstm_scaler = joblib.load(lstm_scaler_path)
        logger.info(" - Loaded LSTM scaler from %s shape=%s", lstm_scaler_path, getattr(mouse_lstm_scaler, "mean_", None).shape)
    except Exception as e:
        logger.warning(" - Failed loading LSTM scaler: %s", e)
        mouse_lstm_scaler = None
else:
    logger.info(" - No LSTM scaler file found in candidates")

# Load LSTM model (preferred: .keras, fallback: .h5)
lstm_model_path = find_lstm_model_path()
if lstm_model_path and tf_load_model:
    mouse_lstm_model = None
    tried = []
    try:
        # If it's a .keras (native Keras) bundle, try it first (most robust)
        if lstm_model_path.endswith(".keras"):
            try:
                mouse_lstm_model = tf_load_model(lstm_model_path)
                logger.info(" - Loaded mouse LSTM model (native .keras) from %s", lstm_model_path)
            except Exception as e_k:
                tried.append(("keras_native", e_k))
                logger.warning(" - Loading .keras failed: %s", e_k)

        # If not loaded yet and we have custom objects helper, try with that
        if mouse_lstm_model is None:
            if _get_keras_custom_objects is not None:
                co = _get_keras_custom_objects()
                # If TF provides custom_object_scope, try using it — some custom ops need the scope.
                try:
                    if custom_object_scope is not None:
                        with custom_object_scope(co):
                            mouse_lstm_model = tf_load_model(lstm_model_path)
                        logger.info(" - Loaded mouse LSTM model using custom_object_scope from %s", lstm_model_path)
                    else:
                        mouse_lstm_model = tf_load_model(lstm_model_path, custom_objects=co)
                        logger.info(" - Loaded mouse LSTM model using custom_objects from %s", lstm_model_path)
                except Exception as e_co:
                    tried.append(("custom_objects", e_co))
                    logger.warning(" - Loading with custom_objects failed: %s", e_co)
                    # try compile=False
                    try:
                        if custom_object_scope is not None:
                            with custom_object_scope(co):
                                mouse_lstm_model = tf_load_model(lstm_model_path, compile=False)
                        else:
                            mouse_lstm_model = tf_load_model(lstm_model_path, custom_objects=co, compile=False)
                        logger.info(" - Loaded mouse LSTM model with compile=False using custom objects from %s", lstm_model_path)
                    except Exception as e_co2:
                        tried.append(("custom_objects_compile_false", e_co2))
                        logger.warning(" - compile=False with custom_objects failed: %s", e_co2)

        # If still not loaded, try plain load_model (last resort)
        if mouse_lstm_model is None:
            try:
                mouse_lstm_model = tf_load_model(lstm_model_path)
                logger.info(" - Loaded mouse LSTM model without custom_objects from %s", lstm_model_path)
            except Exception as e_plain:
                tried.append(("plain_load", e_plain))
                logger.warning(" - Plain load_model failed: %s", e_plain)
                mouse_lstm_model = None

        if mouse_lstm_model is None:
            # Collate and emit a concise warning with the key failure reasons
            reasons = "; ".join([f"{k}:{getattr(v,'__class__',v)}" for k, v in tried])
            logger.warning(" - All attempts to load LSTM model failed: %s", reasons)
    except Exception as outer_exc:
        logger.warning(" - Unexpected error while loading LSTM model: %s", outer_exc)
        mouse_lstm_model = None
elif lstm_model_path:
    logger.info(" - LSTM model file found but tensorflow.keras.load_model unavailable in this env; skipping model load.")
else:
    logger.info(" - No LSTM model file found in candidates")

# meta JSON
meta_candidates = [
    os.path.join(DATA_DIR, "mouse_lstm_meta.json"),
    os.path.join(os.path.dirname(__file__), "..", "data", "mouse_lstm_meta.json"),
    os.path.join(os.path.dirname(__file__), "..", "data", "processed", "mouse_lstm_meta.json"),
]
meta_path = find_existing_file(meta_candidates)
if meta_path:
    try:
        with open(meta_path, "r") as f:
            mouse_lstm_meta = json.load(f)
        logger.info(" - Loaded LSTM meta from %s %s", meta_path, mouse_lstm_meta)
    except Exception as e:
        logger.warning(" - Failed loading LSTM meta: %s", e)
        mouse_lstm_meta = None
else:
    logger.info(" - No LSTM meta found in candidates")

# -------------------------
# Optional: warm up LSTM once at startup to reduce first-request latency
# -------------------------
def _warmup_mouse_lstm():
    try:
        if mouse_lstm_model is None or mouse_lstm_scaler is None or mouse_lstm_meta is None:
            logger.info("LSTM warmup skipped (model/scaler/meta missing).")
            return
        # determine expected dims from scaler/meta
        seq_len = int(mouse_lstm_meta.get("seq_len", 8))
        feat_dim = int(mouse_lstm_meta.get("feat_dim", getattr(mouse_lstm_scaler, "mean_", None).shape[0]))
        import numpy as _np
        X_dummy = _np.zeros((1, seq_len, feat_dim), dtype=float)
        logger.info("Warming mouse LSTM model: seq_len=%s feat_dim=%s", seq_len, feat_dim)
        t0 = time.time()
        try:
            # some TF builds prefer float32 input
            X_try = X_dummy.astype("float32")
            # suppress verbose output
            _ = mouse_lstm_model.predict(X_try, verbose=0)
        except Exception:
            _ = mouse_lstm_model.predict(X_dummy, verbose=0)
        t1 = time.time()
        logger.info("Mouse LSTM warmup done (%.0f ms)", (t1 - t0) * 1000.0)
    except Exception as e:
        logger.warning("Mouse LSTM warmup failed: %s", e)

# start warmup in background thread so it doesn't block startup
try:
    if mouse_lstm_model is not None and mouse_lstm_scaler is not None and mouse_lstm_meta is not None:
        t = threading.Thread(target=_warmup_mouse_lstm, daemon=True)
        t.start()
except Exception as e:
    logger.debug("Failed to start warmup thread: %s", e)

# -------------------------
# Authentication helper decorator (protect endpoints)
# -------------------------
def require_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", None)
        if not auth_header:
            return jsonify({"error": "Token missing"}), 401
        try:
            token = auth_header.split(" ")[1]
            decoded = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            request.user = decoded
        except Exception as e:
            return jsonify({"error": f"Invalid or expired token: {str(e)}"}), 401
        return f(*args, **kwargs)
    return decorated

# -------------------------
# Blocklist (in-memory)
# -------------------------
BLOCKLIST = {}
BLOCKLIST_LOCK = threading.Lock()
DEFAULT_BLOCK_TTL = int(os.environ.get("BLOCK_TTL", 300))

def is_blocked(ip=None, key=None):
    now = time.time()
    with BLOCKLIST_LOCK:
        if ip:
            ts = BLOCKLIST.get(ip)
            if ts and ts > now:
                return True
        if key:
            ts2 = BLOCKLIST.get(key)
            if ts2 and ts2 > now:
                return True
    return False

def add_block(ip=None, key=None, ttl=DEFAULT_BLOCK_TTL):
    unblock_at = time.time() + float(ttl)
    with BLOCKLIST_LOCK:
        if ip:
            BLOCKLIST[ip] = unblock_at
        if key:
            BLOCKLIST[key] = unblock_at

def remove_block(ip=None, key=None):
    with BLOCKLIST_LOCK:
        if ip and ip in BLOCKLIST:
            del BLOCKLIST[ip]
        if key and key in BLOCKLIST:
            del BLOCKLIST[key]

def list_blocks():
    now = time.time()
    with BLOCKLIST_LOCK:
        return {k: v for k, v in BLOCKLIST.items() if v > now}

# -------------------------
# Simple auth + local checks
# -------------------------
def is_request_local(req):
    addr = req.remote_addr
    return addr in ("127.0.0.1", "::1", "localhost")

def check_auth_token_present_and_valid():
    auth_header = request.headers.get("Authorization", None)
    if not auth_header:
        return False
    try:
        token = auth_header.split(" ")[1]
        jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return True
    except Exception:
        return False

# -------------------------
# Quick per-IP sliding window collector config
# -------------------------
_IP_WINDOW_SECONDS = int(os.environ.get("IP_WINDOW_SECONDS", 2))
_IP_WINDOW_MAX = int(os.environ.get("IP_WINDOW_MAX", 8))
_IP_HARD_BLOCK_TTL = int(os.environ.get("IP_HARD_BLOCK_TTL", 300))

_ip_requests = defaultdict(lambda: deque(maxlen=1024))
_ip_lock = threading.Lock()

FLOWCOLLECTOR_FORWARD = os.environ.get("FLOWCOLLECTOR_FORWARD", None)
FLOWCOLLECTOR_TOKEN = os.environ.get("FLOWCOLLECTOR_TOKEN", None)

def forward_to_flowcollector(event):
    if not FLOWCOLLECTOR_FORWARD:
        return
    try:
        headers = {"Content-Type": "application/json"}
        token = FLOWCOLLECTOR_TOKEN
        if token:
            headers["Authorization"] = f"Bearer {token}"
        def _send():
            try:
                requests.post(FLOWCOLLECTOR_FORWARD, json=event, headers=headers, timeout=2.0)
            except Exception as e:
                logger.debug("forward_to_flowcollector failed: %s", e)
        threading.Thread(target=_send, daemon=True).start()
    except Exception:
        pass

# -------------------------
# Inject flow_report.js into all HTML responses (so you don't have to modify templates)
# -------------------------
@app.after_request
def inject_flow_report(response):
    try:
        if response.content_type and response.content_type.startswith("text/html"):
            body = response.get_data(as_text=True)
            # avoid double-inject
            if "id=\"flow-report-js\"" not in body and "</head>" in body:
                script_tag = '<script id="flow-report-js" src="/static/flow_report.js" defer></script></head>'
                injected = body.replace("</head>", script_tag)
                response.set_data(injected)
    except Exception as e:
        logger.debug("inject_flow_report error: %s", e)
    return response

# -------------------------
# Before-request blocklist check (fast)
# -------------------------
@app.before_request
def check_blocklist():
    path = request.path or ""
    if path.startswith("/static") or path.startswith("/socket.io") or path.startswith("/health") or path.startswith("/collect_flow_event"):
        return None

    client_ip = request.headers.get("X-Real-IP", request.remote_addr)
    flow_key = request.headers.get("X-Flow-Key", None) or request.args.get("flow_key")

    if is_blocked(ip=client_ip) or (flow_key and is_blocked(key=flow_key)):
        if check_auth_token_present_and_valid():
            return None
        return jsonify({"error": "Temporarily blocked due to suspicious activity"}), 403

# -------------------------
# Alerts ingest endpoint (FlowCollector -> POSTs alerts here)
# -------------------------
@app.route("/alerts", methods=["POST"])
def ingest_alert():
    if not check_auth_token_present_and_valid() and not is_request_local(request):
        return jsonify({"error": "Unauthorized: token required unless called from localhost"}), 401

    payload = request.get_json(force=True, silent=True) or {}
    try:
        try:
            insert_alert(
                payload.get("type", "external"),
                float(payload.get("prob", payload.get("p", 0.0))),
                payload.get("label", "Unknown"),
                src_ip=(payload.get("meta") or {}).get("src_ip"),
                dst_ip=(payload.get("meta") or {}).get("dst_ip"),
                meta=payload.get("meta", {})
            )
        except Exception:
            logger.debug("insert_alert failed (continuing)")

        try:
            socketio.emit("new_alert", payload)
        except Exception as e:
            logger.warning("socketio emit new_alert failed: %s", e)

        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.exception("ingest_alert failed: %s", e)
        return jsonify({"error": str(e)}), 500


# Quick page-level collector + fast decision

@app.route("/collect_and_check", methods=["POST"])
def collect_and_check():
    evt = request.get_json(force=True) or {}
    client_ip = request.headers.get("X-Real-IP", request.remote_addr)
    now = time.time()

    # attach server-observed fields
    evt.setdefault("timestamp", now)
    evt.setdefault("src_ip", client_ip)
    evt.setdefault("dst_ip", request.host.split(":")[0])
    evt.setdefault("user_agent", request.headers.get("User-Agent", "unknown"))
    evt.setdefault("path", evt.get("path", request.path))

    # check existing blocklist
    if is_blocked(ip=client_ip):
        return jsonify({"error": "blocked", "action": "block"}), 403

    # sliding-window update
    with _ip_lock:
        dq = _ip_requests[client_ip]
        dq.append(now)
        while dq and dq[0] < now - _IP_WINDOW_SECONDS:
            dq.popleft()
        count = len(dq)

    # immediate hard block decision
    if count >= _IP_WINDOW_MAX:
        add_block(ip=client_ip, ttl=_IP_HARD_BLOCK_TTL)
        try:
            insert_alert("realtime_rate_block", 1.0, "Blocked", src_ip=client_ip, meta={"count": count, "window": _IP_WINDOW_SECONDS})
        except Exception:
            logger.debug("insert_alert failed for realtime_rate_block")
        try:
            socketio.emit("new_alert", {"type":"realtime_rate_block","prob":1.0,"label":"Attack","meta":{"src_ip":client_ip,"count":count}})
        except Exception:
            pass
        return jsonify({"action":"block"}), 403

    
    forward_to_flowcollector(evt)

    return jsonify({"action": "ok", "count": count}), 200

# Block / Unblock / Blocks endpoints

@app.route("/block_client", methods=["POST"])
@require_token
def block_client():
    j = request.get_json(force=True, silent=True) or {}
    ip = j.get("ip")
    key = j.get("key")
    ttl = j.get("ttl", DEFAULT_BLOCK_TTL)
    reason = j.get("reason", "manual_block")

    if not ip and not key:
        return jsonify({"error": "Must provide ip or key to block"}), 400

    try:
        add_block(ip=ip, key=key, ttl=ttl)
        alert_payload = {
            "type": "block",
            "ip": ip,
            "key": key,
            "ttl": ttl,
            "reason": reason,
            "time": time.time()
        }
        try:
            insert_alert("manual_block", 1.0, "Blocked", src_ip=ip, dst_ip=None, meta={"reason": reason})
        except Exception:
            logger.debug("insert_alert for block failed (continuing)")
        try:
            socketio.emit("new_alert", alert_payload)
        except Exception:
            logger.debug("socketio emit for block failed")
        return jsonify({"status": "blocked", "entry": alert_payload}), 200
    except Exception as e:
        logger.exception("block_client failed: %s", e)
        return jsonify({"error": str(e)}), 500

@app.route("/unblock_client", methods=["POST"])
@require_token
def unblock_client():
    j = request.get_json(force=True, silent=True) or {}
    ip = j.get("ip")
    key = j.get("key")
    if not ip and not key:
        return jsonify({"error": "Must provide ip or key to unblock"}), 400
    try:
        remove_block(ip=ip, key=key)
        try:
            socketio.emit("new_alert", {"type": "unblock", "ip": ip, "key": key, "time": time.time()})
        except Exception:
            pass
        return jsonify({"status": "unblocked", "ip": ip, "key": key}), 200
    except Exception as e:
        logger.exception("unblock_client failed: %s", e)
        return jsonify({"error": str(e)}), 500

@app.route("/blocks", methods=["GET"])
@require_token
def get_blocks():
    try:
        blocks = list_blocks()
        return jsonify({"blocks": blocks}), 200
    except Exception as e:
        logger.exception("get_blocks failed: %s", e)
        return jsonify({"error": str(e)}), 500

# Health endpoint + flow predict endpoint

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "flow_rf": bool(rf),
        "flow_xgb": bool(xgb_model),
        "mouse_rf": bool(mouse_rf),
        "mouse_lstm": bool(mouse_lstm_model),
        "scaler": bool(scaler)
    })

from flask import current_app

@app.route("/predict_flow", methods=["POST"])
def predict_flow():
    data = request.get_json(force=True)
    features = data.get("features")
    meta = data.get("meta", {}) or {}
    if features is None:
        return jsonify({"error":"Missing features"}),400

    # load and cache feature order + expected dims
    try:
        if not hasattr(predict_flow, "_feat_order"):
            import json, os
            dpath = os.path.join(os.path.dirname(__file__), "..", "data", "processed")
            p1 = os.path.join(dpath, "feature_order_corrected.json")
            p2 = os.path.join(dpath, "feature_order.json")
            fp = p1 if os.path.exists(p1) else p2
            predict_flow._feat_order = json.load(open(fp)) if os.path.exists(fp) else None
            predict_flow._expected = None
            try:
                predict_flow._expected = int(getattr(scaler, "n_features_in_", None) or getattr(scaler, "mean_", None).shape[0])
            except Exception:
                predict_flow._expected = None
    except Exception:
        predict_flow._feat_order = None
        predict_flow._expected = None

    import numpy as _np
    X = None
    try:
        if isinstance(features, dict):
            order = predict_flow._feat_order or list(features.keys())
            vals = [features.get(k, 0) for k in order]
            X = _np.array(vals, dtype=float).reshape(1, -1)
        else:
            arr = _np.array(features, dtype=float).reshape(1, -1)
            if predict_flow._expected and arr.shape[1] != predict_flow._expected:
                if arr.shape[1] < predict_flow._expected:
                    pad = _np.zeros((1, predict_flow._expected - arr.shape[1]), dtype=float)
                    X = _np.hstack([arr, pad])
                else:
                    X = arr[:, :predict_flow._expected]
            else:
                X = arr
    except Exception as e:
        return jsonify({"error":f"Invalid features: {str(e)}"}),400

    try:
        expected = predict_flow._expected
        if expected and X.shape[1] != expected:
            if X.shape[1] < expected:
                pad = _np.zeros((X.shape[0], expected - X.shape[1]), dtype=float)
                X = _np.hstack([X, pad])
            else:
                X = X[:, :expected]
    except Exception:
        pass

    try:
        X_scaled = scaler.transform(X) if scaler is not None else X
    except Exception:
        X_scaled = X

    probs = []
    models_info = {}
    try:
        if rf is not None:
            p_rf = float(rf.predict_proba(X_scaled)[0,1])
            probs.append(p_rf); models_info["rf"] = p_rf
    except Exception as e:
        models_info["rf_error"] = str(e)
    try:
        if xgb_model is not None:
            p_x = float(xgb_model.predict(xgb.DMatrix(X_scaled))[0])
            probs.append(p_x); models_info["xgb"] = p_x
    except Exception as e:
        models_info["xgb_error"] = str(e)

    if not probs:
        return jsonify({"error":"No models available for flow prediction"}),500

    prob_final = float(sum(probs)/len(probs))

    # FORCE default test threshold = 0.5 (no reading of evaluation_summary.json)
    threshold = 0.5

    label = "Attack" if prob_final >= threshold else "Benign"

    out = {"prob_attack": prob_final, "label": label, "meta": meta, "models": models_info}
    try:
        insert_alert("ensemble_flow", float(prob_final), label, src_ip=meta.get("src_ip"), dst_ip=meta.get("dst_ip"), meta=meta)
        socketio.emit("new_alert", {"type":"ensemble_flow","prob":prob_final,"label":label,"meta":meta})
    except Exception:
        pass

    return jsonify(out)


@app.route("/debug_config", methods=["GET"])
def debug_config():
    try:
        import json, os
        dpath = os.path.join(os.path.dirname(__file__), "..", "data", "processed")
        p1 = os.path.join(dpath, "feature_order_corrected.json")
        feat_file = p1 

        mean_shape = None
        try:
            mean_attr = getattr(scaler, "mean_", None)
            if mean_attr is not None:
                try:
                    mean_shape = int(len(mean_attr))
                except Exception:
                    mean_shape = None
            else:
                n_in = getattr(scaler, "n_features_in_", None)
                mean_shape = int(n_in) if (n_in is not None) else None
        except Exception:
            mean_shape = None

        # also expose the effective scaler path if available in this module
        eff_path = None
        try:
            eff_path = globals().get("scaler_path", None)
            if eff_path is None:
                # try common names
                eff_path = globals().get("EFFECTIVE_SCALER_PATH", None) or globals().get("effective_scaler_path", None)
        except Exception:
            eff_path = None

        return jsonify({
            "threshold": 0.5,
            "feature_file": feat_file,
            "scaler_expected_features": mean_shape,
            "effective_scaler_path": eff_path,
            "rf_loaded": bool(rf),
            "xgb_loaded": bool(xgb_model)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500



# -------------------------
# Mouse collection + quick-predict endpoint
# -------------------------
# -------------------------
# Mouse collection + quick-predict endpoint
# -------------------------
# ---- PATCH START ----
# Put these functions where your originals were in backend/app.py

import time as _time
import math as _math

@app.route("/api/collect_mouse", methods=["POST"])
def collect_mouse():
    """
    Keep original behavior but normalize prediction output when predict=True.
    Returns the saved result and, if predicted, a normalized / explicit bot_prob/human_prob fields.
    """
    payload = request.get_json(force=True)
    sid = payload.get("session_id", str(int(_time.time() * 1000)))
    events = payload.get("events", [])
    meta = payload.get("meta", {}) or {}

    # attach client info
    meta.setdefault("user_agent", request.headers.get("User-Agent", "unknown"))
    meta.setdefault("client_ip", request.remote_addr)

    # save raw events (DB function)
    try:
        save_mouse(sid, events, meta)
    except Exception as e:
        logger.warning("save_mouse failed: %s", e)

    result = {"status": "saved", "session_id": sid, "meta": meta, "events_count": len(events)}

    if payload.get("predict", False):
        t0 = _time.time()
        try:
            pred = _predict_mouse_from_events(events)
            t1 = _time.time()
            latency_ms = int((t1 - t0) * 1000.0)
            # Normalize output: ensure bot_prob & human_prob explicit
            bot = None
            human = None
            # prefer explicit fields returned by model
            if isinstance(pred, dict):
                # possible fields
                bot = pred.get("bot_prob") or pred.get("botProb") or pred.get("bot") or pred.get("confidence")
                human = pred.get("human_prob") or pred.get("humanProb") or pred.get("human")
                # if there is human but not bot, invert
                if bot is None and human is not None:
                    try:
                        bot = 1.0 - float(human)
                    except Exception:
                        bot = None
                # if confidence present but ambiguous, try to infer from label
                if bot is None and pred.get("confidence") is not None:
                    try:
                        conf = float(pred.get("confidence"))
                        # if label explicitly "human" but conf > 0.5, assume conf was human_prob -> invert
                        lbl = str(pred.get("label") or pred.get("prediction") or "").lower()
                        if lbl == "human" and conf > 0.5:
                            bot = 1.0 - conf
                        else:
                            bot = conf
                    except Exception:
                        pass
            # if still None and RF/LSTM probs present in details/per-window, average them
            if bot is None and isinstance(pred, dict) and pred.get("details"):
                try:
                    per = pred["details"].get("per_window", [])
                    vals = []
                    for w in per:
                        if isinstance(w, dict):
                            if w.get("avg") is not None:
                                vals.append(float(w.get("avg")))
                            else:
                                for kk in ("rf","lstm"):
                                    if w.get(kk) is not None:
                                        vals.append(float(w.get(kk)))
                    if vals:
                        bot = float(sum(vals) / len(vals))
                except Exception:
                    bot = None

            # final fallback: if label exists, map to 1/0
            if bot is None:
                lbl = ""
                try:
                    lbl = str(pred.get("label") or pred.get("prediction") or "").lower()
                except Exception:
                    lbl = ""
                if lbl == "bot" or lbl == "attack" or lbl == "1":
                    bot = 0.99
                elif lbl == "human" or lbl == "benign" or lbl == "0":
                    bot = 0.01
                else:
                    bot = 0.05

            # clamp
            try:
                bot = float(bot)
            except Exception:
                bot = 0.05
            bot = max(0.0, min(1.0, bot))
            human = 1.0 - bot

            # canonical result
            canonical = {
                "label": pred.get("label") if isinstance(pred, dict) else (pred if isinstance(pred, str) else None),
                "bot_prob": bot,
                "human_prob": human,
                "confidence": bot,
                "confidence_is": "bot_prob",
                "_server_latency_ms": latency_ms,
                "raw": pred
            }

            result["prediction"] = canonical

            # persist and emit
            try:
                insert_alert("mouse_heuristic", float(bot), canonical["label"] or ("bot" if bot>=0.5 else "human"), meta={"session_id": sid, **meta})
            except Exception:
                pass

            try:
                socketio.emit("mouse_prediction", {"session_id": sid, "prediction": canonical, "meta": meta})
            except Exception:
                logger.debug("socketio emit mouse_prediction failed")
        except Exception as e:
            logger.exception("collect_mouse prediction error: %s", e)
            result["prediction_error"] = str(e)
            result["prediction_error_trace"] = traceback.format_exc()

    return jsonify(result)


@app.route("/api/predict_mouse", methods=["POST"])
def predict_mouse():
    """
    Normalize _predict_mouse_from_events output so frontend receives explicit bot_prob/human_prob/confidence fields.
    """
    payload = request.get_json(force=True)
    events = payload.get("events", [])
    if not events:
        return jsonify({"error": "Missing events"}), 400

    t0 = _time.time()
    try:
        pred = _predict_mouse_from_events(events)
    except Exception as e:
        logger.exception("prediction failed")
        return jsonify({"error": f"Prediction failed: {str(e)}"}), 500
    t1 = _time.time()
    latency_ms = int((t1 - t0) * 1000.0)

    # Build canonical normalized object (same logic as in collect_mouse)
    bot = None
    human = None
    if isinstance(pred, dict):
        bot = pred.get("bot_prob") or pred.get("botProb") or pred.get("bot") or pred.get("confidence")
        human = pred.get("human_prob") or pred.get("humanProb") or pred.get("human")
        if bot is None and human is not None:
            try:
                bot = 1.0 - float(human)
            except Exception:
                bot = None
        if bot is None and pred.get("confidence") is not None:
            try:
                conf = float(pred.get("confidence"))
                lbl = str(pred.get("label") or pred.get("prediction") or "").lower()
                if lbl == "human" and conf > 0.5:
                    bot = 1.0 - conf
                else:
                    bot = conf
            except Exception:
                pass

    # per-window average fallback
    if bot is None and isinstance(pred, dict) and pred.get("details"):
        try:
            per = pred["details"].get("per_window", [])
            vals = []
            for w in per:
                if isinstance(w, dict):
                    if w.get("avg") is not None:
                        vals.append(float(w.get("avg")))
                    else:
                        for kk in ("rf","lstm"):
                            if w.get(kk) is not None:
                                vals.append(float(w.get(kk)))
            if vals:
                bot = float(sum(vals) / len(vals))
        except Exception:
            bot = None

    if bot is None:
        lbl = ""
        try:
            lbl = str(pred.get("label") or pred.get("prediction") or "").lower()
        except Exception:
            lbl = ""
        if lbl == "bot" or lbl == "attack" or lbl == "1":
            bot = 0.99
        elif lbl == "human" or lbl == "benign" or lbl == "0":
            bot = 0.01
        else:
            bot = 0.05

    try:
        bot = float(bot)
    except Exception:
        bot = 0.05
    bot = max(0.0, min(1.0, bot))
    human = 1.0 - bot

    out = {
        "label": pred.get("label") if isinstance(pred, dict) else (pred if isinstance(pred, str) else None),
        "bot_prob": bot,
        "human_prob": human,
        "confidence": bot,
        "confidence_is": "bot_prob",
        "_server_latency_ms": latency_ms,
        "models": pred.get("models") if isinstance(pred, dict) and pred.get("models") else pred.get("models") if isinstance(pred, dict) else None,
        "details": pred.get("details") if isinstance(pred, dict) else None,
        "raw": pred
    }

    try:
        insert_alert("mouse_heuristic", float(bot), out["label"] or ("bot" if bot>=0.5 else "human"), meta={"session_id": payload.get("session_id")})
    except Exception:
        pass

    try:
        socketio.emit("mouse_prediction", {"session_id": payload.get("session_id"), "prediction": out})
    except Exception:
        logger.debug("socketio emit mouse_prediction failed")

    return jsonify(out)

# ---- PATCH END ----

# -------------------------
# Internal mouse prediction logic (full implementation)
# -------------------------
def _predict_mouse_from_events(events,
                               window_size=None,
                               stride=None,
                               min_events=40,
                               threshold=0.65,
                               min_windows_above_thresh=2):
    """
    Robust mouse prediction returning canonicalized JSON via _canonical_mouse_resp.
    """
    start_ts = time.time()
    # basic checks
    if events is None or len(events) == 0:
        raise ValueError("No events provided")

    if mouse_lstm_meta and window_size is None:
        window_size = int(mouse_lstm_meta.get("window", 10))
    if window_size is None:
        window_size = 10

    if stride is None:
        stride = max(1, window_size // 2)

    # if too few raw events, avoid unstable predictions — return low-confidence human
    if len(events) < min_events:
        # try a quick heuristic: still allow RF if available but mark low confidence
        try:
            feats = extract_features_from_events(events)
            X_full = np.array(feats).reshape(1, -1)

            try:
                X = X_full[:, selected_indices]
            except Exception:
                X = X_full
            Xs = mouse_scaler.transform(X) if mouse_scaler is not None else X
            prob_rf = float(mouse_rf.predict_proba(Xs)[0, 1]) if mouse_rf is not None else None
        except Exception:
            prob_rf = None

        confidence = prob_rf if prob_rf is not None else 0.05
        label = "bot" if confidence >= (threshold + 0.05) else "human"
        result = {
            "label": label,
            "confidence": float(confidence),
            "models": (["rf"] if prob_rf is not None else []),
            "details": {"reason": "insufficient_events", "n_events": len(events)}
        }
        return _canonical_mouse_resp(result, start_ts)

    # build windows
    windows = []
    for i in range(0, max(1, len(events) - window_size + 1), stride):
        w = events[i:i+window_size]
        feats = extract_features_from_events(w)
        windows.append(np.asarray(feats, dtype=float))
    # if windows is empty (very short), fallback to whole session features
    if len(windows) == 0:
        windows = [np.asarray(extract_features_from_events(events), dtype=float)]

    # prepare arrays
    probs_per_window = []   # list of averaged probs per window
    model_sources = set()
    details = {"window_count": len(windows), "per_window": []}

    for w_vec in windows:
        try:
            Xw = np.array(w_vec, dtype=float).reshape(1, -1)[:, selected_indices]
        except Exception:
            Xw = np.asarray(w_vec).reshape(1, -1)

        try:
            Xw_sel = Xw[:, selected_indices]
        except Exception:
            Xw_sel = Xw

        # RF branch
        prob_rf = None
        try:
            if mouse_rf is not None and mouse_scaler is not None:
                Xw_rf = mouse_scaler.transform(Xw_sel)
            elif mouse_rf is not None:
                Xw_rf = Xw_sel
            else:
                Xw_rf = None

            if Xw_rf is not None and mouse_rf is not None:
                prob_rf = float(mouse_rf.predict_proba(Xw_rf)[0, 1])
                model_sources.add("rf")
        except Exception:
            prob_rf = None

        # LSTM branch (build sequence when possible)
        prob_lstm = None
        try:
            if mouse_lstm_model is not None and mouse_lstm_scaler is not None and mouse_lstm_meta is not None:
                expected_dim = getattr(mouse_lstm_scaler, "mean_", None).shape[0]
                if Xw_sel.shape[1] == expected_dim:
                    # scale and create seq shape (1, seq_len, feat_dim)
                    seq_len = int(mouse_lstm_meta.get("seq_len", 8))
                    feat_dim = int(mouse_lstm_meta.get("feat_dim", Xw_sel.shape[1]))
                    Xw_scaled = mouse_lstm_scaler.transform(Xw_sel)
                    # pad/truncate simple approach: repeat or zero-pad to reach seq_len
                    if Xw_scaled.shape[0] >= seq_len:
                        X_seq = Xw_scaled[:seq_len].reshape(1, seq_len, feat_dim)
                    else:
                        pad = np.zeros((seq_len - Xw_scaled.shape[0], feat_dim), dtype=float)
                        X_seq = np.vstack([Xw_scaled, pad]).reshape(1, seq_len, feat_dim)
                    p = mouse_lstm_model.predict(X_seq)
                    prob_lstm = float(p.reshape(-1)[0])
                    model_sources.add("lstm")
        except Exception:
            prob_lstm = None

        # combine available probs for this window
        window_probs = [p for p in (prob_rf, prob_lstm) if p is not None]
        avg_p = float(sum(window_probs) / len(window_probs)) if window_probs else None
        probs_per_window.append(avg_p)
        details["per_window"].append({"rf": prob_rf, "lstm": prob_lstm, "avg": avg_p})

    # filter None windows (shouldn't happen often)
    valid_probs = [p for p in probs_per_window if p is not None]
    if len(valid_probs) == 0:
        result = {
            "label": "human",
            "confidence": 0.05,
            "models": list(model_sources),
            "details": {
                "n_events": len(events),
                "window_size": window_size,
                "stride": stride,
                "n_windows": len(windows),
                "windows_above_threshold": 0,
                "per_window": details["per_window"],
                "reason": "no_valid_model_predictions"
            }
        }
        return _canonical_mouse_resp(result, start_ts)

    avg_confidence = float(sum(valid_probs) / len(valid_probs))
    windows_above = sum(1 for p in valid_probs if p >= threshold)

    # Hysteresis: require average >= threshold AND at least min_windows_above_thresh windows above threshold
    label = "bot" if (avg_confidence >= threshold and windows_above >= min_windows_above_thresh) else "human"

    result = {
        "label": label,
        "confidence": avg_confidence,
        "models": list(model_sources),
        "details": {
            "n_events": len(events),
            "window_size": window_size,
            "stride": stride,
            "n_windows": len(windows),
            "windows_above_threshold": int(windows_above),
            "per_window": details["per_window"]
        }
    }
    return _canonical_mouse_resp(result, start_ts)

# -------------------------
# Combined prediction endpoint (flow + mouse ensemble)
# -------------------------
@app.route("/api/predict_combined", methods=["POST"])
def predict_combined():
    """
    Accepts JSON:
      { flow: {features: [...]}, mouse: {events: [...]}, weights: {flow:0.5, mouse:0.5}, meta: {...} }

    Returns:
      {
        "flow_prob": <0..1 or null>,
        "mouse_prob": <0..1 or null>,
        "final_prob": <0..1>,
        "bot_prob": <0..1>,         # alias of final_prob (explicit)
        "human_prob": <0..1>,       # 1 - bot_prob
        "confidence": <0..1>,       # same as bot_prob for compatibility
        "confidence_is": "bot_prob",
        "label": "Attack/Bot"|"Normal/Human",
        "weights": {...},
        "models": ["flow","mouse"]   # which subsystems contributed
      }
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        flow_data = (data.get("flow") or {}).get("features")
        mouse_events = (data.get("mouse") or {}).get("events", [])
        weights = data.get("weights", {"flow": 0.5, "mouse": 0.5}) or {"flow": 0.5, "mouse": 0.5}
        meta = data.get("meta", {}) or {}

        # normalize weights to numeric defaults
        try:
            w_flow = float(weights.get("flow", 0.5))
        except Exception:
            w_flow = 0.5
        try:
            w_mouse = float(weights.get("mouse", 0.5))
        except Exception:
            w_mouse = 0.5

        # FLOW
        prob_flow = None
        models_used = []
        if flow_data is not None:
            try:
                X_flow = np.array(flow_data).reshape(1, -1)
                X_flow_scaled = scaler.transform(X_flow) if scaler is not None else X_flow
                preds = []
                if rf is not None:
                    try:
                        preds.append(float(rf.predict_proba(X_flow_scaled)[0, 1]))
                        models_used.append("flow_rf")
                    except Exception:
                        logger.debug("flow rf predict failed", exc_info=True)
                if xgb_model is not None:
                    try:
                        preds.append(float(xgb_model.predict(xgb.DMatrix(X_flow_scaled))[0]))
                        models_used.append("flow_xgb")
                    except Exception:
                        logger.debug("flow xgb predict failed", exc_info=True)
                if preds:
                    prob_flow = float(sum(preds) / len(preds))
            except Exception as e:
                logger.warning("Flow processing error: %s", e)

        # MOUSE
        prob_mouse = None
        if mouse_events:
            try:
                feats = extract_features_from_events(mouse_events)
                X_mouse = np.array(feats).reshape(1, -1)
            except Exception as e:
                logger.warning("Failed to extract mouse features: %s", e)
                X_mouse = None

            prob_mouse_rf = None
            prob_mouse_lstm = None

            # RF
            try:
                if X_mouse is not None and mouse_rf is not None:
                    X_rf = mouse_scaler.transform(X_mouse) if mouse_scaler is not None else X_mouse
                    prob_mouse_rf = float(mouse_rf.predict_proba(X_rf)[0, 1])
                    models_used.append("mouse_rf")
            except Exception as e:
                logger.debug("mouse RF error: %s", e)

            # LSTM
            try:
                if (
                    X_mouse is not None
                    and mouse_lstm_model is not None
                    and mouse_lstm_scaler is not None
                    and mouse_lstm_meta is not None
                ):
                    expected_dim = getattr(mouse_lstm_scaler, "mean_", None).shape[0] if getattr(mouse_lstm_scaler, "mean_", None) is not None else None
                    if expected_dim is not None and X_mouse.shape[1] != expected_dim:
                        raise ValueError(f"LSTM scaler expects {expected_dim} features but got {X_mouse.shape[1]}")
                    seq_len = int(mouse_lstm_meta.get("seq_len", 8))
                    feat_dim = int(mouse_lstm_meta.get("feat_dim", X_mouse.shape[1]))
                    X_scaled = mouse_lstm_scaler.transform(X_mouse)
                    if pad_sequences is not None:
                        X_seq = pad_sequences([X_scaled], maxlen=seq_len, dtype="float32", padding="post", truncating="post")
                    else:
                        if X_scaled.shape[0] >= seq_len:
                            X_seq = X_scaled[:seq_len].reshape(1, seq_len, feat_dim)
                        else:
                            pad = np.zeros((seq_len - X_scaled.shape[0], feat_dim), dtype=float)
                            X_seq = np.vstack([X_scaled, pad]).reshape(1, seq_len, feat_dim)
                    p = mouse_lstm_model.predict(X_seq)
                    prob_mouse_lstm = float(p.reshape(-1)[0])
                    models_used.append("mouse_lstm")
            except Exception as e:
                logger.debug("mouse LSTM inference skipped: %s", e)

            probs = [p for p in (prob_mouse_rf, prob_mouse_lstm) if p is not None]
            if probs:
                prob_mouse = float(sum(probs) / len(probs))

        # Final ensemble: combine only available contributions and weight them properly
        parts = []
        denom = 0.0
        if prob_flow is not None:
            parts.append(w_flow * prob_flow)
            denom += w_flow
        if prob_mouse is not None:
            parts.append(w_mouse * prob_mouse)
            denom += w_mouse

        if denom == 0.0:
            return jsonify({"error": "No input data provided for flow or mouse"}), 400

        final_prob = float(sum(parts) / denom)
        # canonical fields
        bot_prob = final_prob
        human_prob = 1.0 - bot_prob
        confidence = bot_prob
        confidence_is = "bot_prob"

        label = "Attack/Bot" if bot_prob >= 0.5 else "Normal/Human"

        # persist + emit
        try:
            insert_alert("ensemble_combined", float(bot_prob), label,
                         src_ip=meta.get("src_ip"), dst_ip=meta.get("dst_ip"), meta=meta)
            socketio.emit("new_alert", {"type": "ensemble_combined", "prob": bot_prob, "label": label, "meta": meta})
        except Exception as e:
            logger.warning("Failed to insert/emit combined alert: %s", e)

        resp = {
            "flow_prob": prob_flow,
            "mouse_prob": prob_mouse,
            "final_prob": final_prob,
            "bot_prob": bot_prob,
            "human_prob": human_prob,
            "confidence": confidence,
            "confidence_is": confidence_is,
            "label": label,
            "weights": {"flow": w_flow, "mouse": w_mouse},
            "models": list(dict.fromkeys(models_used))  # dedupe preserving order
        }
        return jsonify(resp)

    except Exception as e:
        logger.exception("predict_combined failed")
        return jsonify({"error": str(e)}), 500

# -------------------------
# Admin status endpoint
# -------------------------
@app.route("/admin/model_status")
def admin_model_status():
    status = {
        "flow_rf": getattr(rf, "n_features_in_", None),
        "flow_xgb": bool(xgb_model),
        "mouse_rf": getattr(mouse_rf, "n_features_in_", None),
        "mouse_scaler": getattr(mouse_scaler, "mean_", None).shape if mouse_scaler is not None else None,
        "mouse_lstm_model": bool(mouse_lstm_model),
        "mouse_lstm_scaler": getattr(mouse_lstm_scaler, "mean_", None).shape if mouse_lstm_scaler is not None else None,
        "mouse_lstm_meta": mouse_lstm_meta,
        "flow_scaler": getattr(scaler, "mean_", None).shape if scaler is not None else None
    }
    status["paths_checked"] = {
        "mouse_lstm_scaler_processed": os.path.abspath(os.path.join(DATA_DIR, "mouse_lstm_scaler.save")),
        "mouse_lstm_scaler_data": os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "mouse_lstm_scaler.save")),
        "mouse_lstm_model": os.path.abspath(lstm_model_path) if lstm_model_path else None,
        "flow_scaler_candidates": [os.path.abspath(p) for p in [
            flow_paths.get("scaler"),
            os.path.join(os.path.dirname(__file__), "..", "data", "scaler_used.save"),
            os.path.join(os.path.dirname(__file__), "..", "data", "processed", "scaler_used.save"),
            os.path.join(os.path.dirname(__file__), "..", "data", "scaler.save"),
            os.path.join(os.path.dirname(__file__), "..", "data", "processed", "scaler.save"),
            os.path.join(DATA_DIR, "scaler_used.save"),
            os.path.join(DATA_DIR, "scaler.save"),
        ]]
    }
    return jsonify(status)

# -------------------------
# Serve frontend static files
# -------------------------
@app.route("/static/<path:filename>")
def static_files(filename):
    front = os.path.join(ROOT, "frontend")
    return send_from_directory(front, filename)

@app.route("/")
def render_home():
    index_path = os.path.join(ROOT, "frontend", "index.html")
    if os.path.exists(index_path):
        return send_from_directory(os.path.join(ROOT, "frontend"), "index.html")
    return send_from_directory(app.static_folder, 'index.html')

@app.route("/login")
def render_login():
    tpl = os.path.join(os.path.dirname(__file__), "templates", "login.html")
    if os.path.exists(tpl):
        return render_template("login.html")
    return "Login Page (template missing)"

@app.route("/register")
def render_register():
    tpl = os.path.join(os.path.dirname(__file__), "templates", "register.html")
    if os.path.exists(tpl):
        return render_template("register.html")
    return "Register Page (template missing)"

@app.route("/dashboard")
def render_dashboard():
    tpl = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    if os.path.exists(tpl):
        return render_template("dashboard.html")
    return send_from_directory(app.static_folder, 'index.html')

@app.route("/mouse_test")
def render_mouse_test():
    tpl = os.path.join(os.path.dirname(__file__), "templates", "mouse_test.html")
    if os.path.exists(tpl):
        return render_template("mouse_test.html")
    return "mouse_test (template missing)"

@app.after_request
def remove_csp(response):
    if "Content-Security-Policy" in response.headers:
        del response.headers["Content-Security-Policy"]
    if "Permissions-Policy" in response.headers:
        del response.headers["Permissions-Policy"]
    if "X-Frame-Options" in response.headers:
        del response.headers["X-Frame-Options"]
    return response

# Register auth blueprint (login/register)
try:
    app.register_blueprint(auth_bp, url_prefix="/auth")
except Exception as e:
    logger.warning("Failed to register auth_bp: %s", e)

# -------------------------
# SocketIO events (basic)
# -------------------------
def register_socket_handlers(sio):
    from flask import request as flask_request
    from flask_socketio import emit as socket_emit

    @sio.on("connect")
    def _on_connect():
        logger.info("Socket connected: %s", flask_request.sid if hasattr(flask_request, "sid") else "unknown")
        try:
            socket_emit("connected", {"msg": "Welcome", "sid": getattr(flask_request, "sid", None)})
        except Exception:
            pass

    @sio.on("ping_models")
    def _on_ping_models(data):
        try:
            server_name = os.uname().nodename if hasattr(os, "uname") else "localhost"
        except Exception:
            server_name = "localhost"
        socket_emit("model_status", {"health": "ok", "server": server_name})

try:
    register_socket_handlers(socketio)
except Exception as _e:
    logger.warning("register_socket_handlers failed at import-time: %s", _e)

from flask import request as _flask_request, jsonify as _jsonify

def is_automation(req):
    ua = req.headers.get("User-Agent", "").lower()
    webdriver = req.headers.get("X-Requested-With", "")
    bad_keywords = [
        "selenium", "webdriver", "headless", "phantomjs",
        "puppeteer", "playwright", "automation"
    ]

    if any(k in ua for k in bad_keywords):
        return True

    if req.headers.get("Sec-Fetch-Mode", "") == "navigate" and "chrome" not in ua:
        return True

    # Selenium often sends this header
    if req.headers.get("X-Selenium") == "1":
        return True

    return False

@app.before_request
def block_automation():
    if request.path.startswith("/static") or request.path.startswith("/socket.io"):
        return None  

    if is_automation(request):
        return jsonify({"error": "Automation detected. Request blocked."}), 403
    
@app.route('/db_health')
def db_health():
    try:
        from db import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.fetchone()
        cur.close()
        conn.close()
        return {"db": "ok"}
    except Exception as e:
        return {"db": "error", "details": str(e)}, 500

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development") == "development"
    logger.info("Starting app: host=%s port=%s debug=%s", host, port, debug)
    socketio.run(app, host=host, port=port, debug=debug)