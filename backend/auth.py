# backend/auth.py

import os
import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict
from flask import Blueprint, request, jsonify, current_app, render_template, redirect, url_for
import bcrypt
import jwt
from dotenv import load_dotenv

load_dotenv()


SECRET_KEY = os.environ.get("SECRET_KEY") or os.environ.get("JWT_SECRET") or os.urandom(24).hex()
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRES_HOURS = int(os.environ.get("JWT_EXPIRES_HOURS", "8"))
JWT_REFRESH_EXPIRES_DAYS = int(os.environ.get("JWT_REFRESH_EXPIRES_DAYS", "7"))


DESIRED_BCRYPT_ROUNDS = int(os.environ.get("BCRYPT_ROUNDS", 12))

logger = logging.getLogger("ai_ml_cyberdefense.auth")
logger.setLevel(os.environ.get("AUTH_LOG_LEVEL", "INFO"))

auth_bp = Blueprint("auth", __name__, template_folder="templates")

# import DB models / helpers (uses backend/db.py)
from backend.db import get_db_session, User, store_refresh_jti, revoke_refresh_jti, is_refresh_revoked

# ---------- password policy (server-side) ----------
ALLOWED_SPECIALS = r"!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/\?`~"
_allowed_chars_re = re.compile(r"^[A-Za-z0-9" + ALLOWED_SPECIALS + r"]+$")
_has_letter_re = re.compile(r"[A-Za-z]")
_has_digit_re = re.compile(r"[0-9]")
_has_special_re = re.compile("[" + ALLOWED_SPECIALS + "]")

def validate_password(pw: str) -> Tuple[bool, str]:
    if not pw or not isinstance(pw, str):
        return False, "Password required"
    if len(pw) < 8:
        return False, "Password must be at least 8 characters long"
    if not _allowed_chars_re.match(pw):
        return False, "Password contains invalid characters (no spaces allowed)"
    if not _has_letter_re.search(pw):
        return False, "Password must include at least one letter (a–z/A–Z)"
    if not _has_digit_re.search(pw):
        return False, "Password must include at least one number (0–9)"
    if not _has_special_re.search(pw):
        return False, "Password must include at least one special character (e.g. !@#$%)"
    return True, ""


def hash_password(password: str, rounds: int = DESIRED_BCRYPT_ROUNDS) -> str:

    if isinstance(password, str):
        password = password.encode("utf-8")
    h = bcrypt.hashpw(password, bcrypt.gensalt(rounds=rounds))
    return h.decode("utf-8")

def needs_rehash(stored_hash: str, desired_rounds: int = DESIRED_BCRYPT_ROUNDS) -> bool:
    try:
        parts = stored_hash.split("$")
        if len(parts) < 3:
            return True
        cost = int(parts[2])
        return cost < desired_rounds
    except Exception:
        return True

def generate_jwt(payload: dict, expires_delta: Optional[timedelta] = None, typ: str = "access") -> str:

    p = payload.copy()
    if expires_delta is None:
        if typ == "refresh":
            expires_delta = timedelta(days=JWT_REFRESH_EXPIRES_DAYS)
        else:
            expires_delta = timedelta(hours=JWT_EXPIRES_HOURS)
    exp = datetime.utcnow() + expires_delta
    p.update({"exp": exp, "typ": typ})
    if typ == "refresh" and "jti" not in p:
        p["jti"] = str(uuid.uuid4())
    token = jwt.encode(p, SECRET_KEY, algorithm=JWT_ALGORITHM)
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token

def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise
    except jwt.InvalidTokenError:
        raise

#DB helpers: create/verify users
def create_user(username: str, password: str, email: Optional[str] = None) -> dict:
    session = get_db_session()
    try:
        existing = session.query(User).filter(User.username == username).first()
        if existing:
            raise ValueError("username_exists")

        
        pwd_hash = hash_password(password, rounds=DESIRED_BCRYPT_ROUNDS)

        u = User(
            username=username,
            password_hash=pwd_hash,
            email=email
        )
        session.add(u)
        session.commit()
        session.refresh(u)
        return {"id": u.id, "username": u.username, "email": u.email, "created_at": u.created_at.isoformat()}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def verify_user_credentials(username: str, password: str) -> Optional[dict]:
    session = get_db_session()
    try:
        u = session.query(User).filter(User.username == username).first()
        if not u:
            return None
        stored_hash = u.password_hash
        if not stored_hash:
            return None
        stored_hash_bytes = stored_hash.encode("utf-8")
        password_bytes = password.encode("utf-8") if isinstance(password, str) else password

        try:
            ok = bcrypt.checkpw(password_bytes, stored_hash_bytes)
        except Exception:
            ok = False

        if not ok:
            return None

        try:
            if needs_rehash(stored_hash, DESIRED_BCRYPT_ROUNDS):
                try:
                    new_hash = hash_password(password, rounds=DESIRED_BCRYPT_ROUNDS)
                    u.password_hash = new_hash
                    session.add(u)
                    session.commit()
                    logger.info("Upgraded bcrypt cost for user=%s", username)
                except Exception as _e:
                    session.rollback()
                    logger.warning("Failed to upgrade bcrypt hash for user=%s: %s", username, _e)
        except Exception:
            logger.debug("rehash check failed for user=%s", username)

        return {"id": u.id, "username": u.username, "email": u.email}
    finally:
        session.close()

def _is_browser_html_request(req) -> bool:
    return req.accept_mimetypes.accept_html and not req.is_json

@auth_bp.route("/register", methods=["GET", "POST"])
def route_register():
    if request.method == "GET":
        try:
            return render_template("register.html")
        except Exception:
            return

    try:
        payload = request.get_json(silent=True) or request.form
        username = (payload.get("username") or "").strip()
        password = payload.get("password") or ""
        email = payload.get("email") or None

        if not username or not password:
            if _is_browser_html_request(request):
                return render_template("register.html", error="username and password required"), 400
            return jsonify({"error": "username and password required"}), 400

        ok, reason = validate_password(password)
        if not ok:
            if _is_browser_html_request(request):
                return render_template("register.html", error=reason), 400
            return jsonify({"error": "weak_password", "message": reason}), 400

        try:
            user = create_user(username=username, password=password, email=email)
        except ValueError as e:
            if str(e) == "username_exists":
                if _is_browser_html_request(request):
                    return render_template("register.html", error="username already exists"), 409
                return jsonify({"error": "username_exists"}), 409
            raise

        if _is_browser_html_request(request):
            return redirect(url_for("auth.route_login"))
        return jsonify({"status": "ok", "user": {"id": user["id"], "username": user["username"], "email": user["email"]}}), 201

    except Exception as e:
        logger.exception("register failed: %s", e)
        if _is_browser_html_request(request):
            return render_template("register.html", error="internal error"), 500
        return jsonify({"error": str(e)}), 500

@auth_bp.route("/login", methods=["GET", "POST"])
def route_login():
    if request.method == "GET":
        try:
            return render_template("login.html")
        except Exception:
            return 

    try:
        payload = request.get_json(silent=True) or request.form
        username = (payload.get("username") or "").strip()
        password = payload.get("password") or ""
        if not username or not password:
            if _is_browser_html_request(request):
                return render_template("login.html", error="username/password required"), 400
            return jsonify({"error": "username and password required"}), 400

        user = verify_user_credentials(username, password)
        if not user:
            if _is_browser_html_request(request):
                return render_template("login.html", error="invalid credentials"), 401
            return jsonify({"error": "invalid_credentials"}), 401

        access_token = generate_jwt({"sub": user["id"], "username": user["username"]}, expires_delta=timedelta(hours=JWT_EXPIRES_HOURS), typ="access")
        refresh_token = generate_jwt({"sub": user["id"], "username": user["username"]}, expires_delta=timedelta(days=JWT_REFRESH_EXPIRES_DAYS), typ="refresh")

        try:
            payload_rt = jwt.decode(refresh_token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
            jti = payload_rt.get("jti")
            exp_ts = datetime.utcfromtimestamp(payload_rt.get("exp")) if payload_rt.get("exp") else None
            
            store_refresh_jti(jti, expires_at=exp_ts, meta={"user_id": user["id"], "username": user["username"]})
        except Exception as e:
            logger.warning("Could not persist refresh jti: %s", e)

        if _is_browser_html_request(request):
            return redirect(url_for("dashboard"))
        return jsonify({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in_hours": JWT_EXPIRES_HOURS,
            "user": {"id": user["id"], "username": user["username"]}
        })

    except Exception as e:
        logger.exception("login failed: %s", e)
        if _is_browser_html_request(request):
            return render_template("login.html", error="internal error"), 500
        return jsonify({"error": str(e)}), 500

@auth_bp.route("/whoami", methods=["GET"])
def route_whoami():
    auth_header = request.headers.get("Authorization", None)
    if not auth_header:
        return jsonify({"error": "Token missing"}), 401
    try:
        token = auth_header.split(" ")[1]
        decoded = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return jsonify({"user": decoded})
    except Exception as e:
        return jsonify({"error": "invalid_token", "detail": str(e)}), 401

@auth_bp.route("/refresh", methods=["POST"])
def refresh_token():
    data = request.get_json(silent=True) or {}
    refresh = data.get("refresh_token") or data.get("refresh")
    if not refresh:
        return jsonify({"error":"missing refresh token"}), 400
    try:
        payload = decode_token(refresh)
    except jwt.ExpiredSignatureError:
        return jsonify({"error":"refresh token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error":"invalid token"}), 401

    jti = payload.get("jti")
    if not jti or is_refresh_revoked(jti):
        return jsonify({"error":"revoked"}), 401

    user_id = payload.get("sub")
    username = payload.get("username")
    
    new_access = generate_jwt({"sub": user_id, "username": username}, expires_delta=timedelta(hours=JWT_EXPIRES_HOURS), typ="access")
    return jsonify({"access_token": new_access}), 200

@auth_bp.route("/logout", methods=["POST"])
def logout():
    data = request.get_json(silent=True) or {}
    refresh = data.get("refresh_token") or data.get("refresh")
    if not refresh:
        auth_header = request.headers.get("Authorization", "")
        if auth_header and " " in auth_header:
            token = auth_header.split(" ", 1)[1]
            try:
                payload = decode_token(token)
                jti = payload.get("jti")
                if jti:
                    revoke_refresh_jti(jti)
                    return jsonify({"status":"ok"}), 200
            except Exception:
                pass
        return jsonify({"error":"missing refresh token"}), 400

    try:
        payload = decode_token(refresh)
    except jwt.InvalidTokenError:
        return jsonify({"error":"invalid token"}), 400

    jti = payload.get("jti")
    if jti:
        try:
            revoke_refresh_jti(jti)
        except Exception as e:
            logger.warning("Failed to revoke refresh jti: %s", e)
            
    return jsonify({"status":"ok"}), 200