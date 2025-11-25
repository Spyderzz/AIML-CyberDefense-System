import hashlib, json
from flask import current_app

def sign_session(data: dict) -> str:
    secret = current_app.config["SECRET_KEY"]
    raw = json.dumps(data, sort_keys=True, separators=(',',':'))
    return hashlib.sha256((raw + secret).encode()).hexdigest()

def verify_signature(data: dict, signature: str) -> bool:
    return sign_session(data) == signature
