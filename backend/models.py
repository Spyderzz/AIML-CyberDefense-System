# backend/models.py

from flask_sqlalchemy import SQLAlchemy  # type: ignore
from datetime import datetime
db = SQLAlchemy()

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(200), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Alert(db.Model):
    __tablename__ = "alerts"
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(80), nullable=False) 
    score = db.Column(db.Float, nullable=False)
    label = db.Column(db.String(32), nullable=False)
    src_ip = db.Column(db.String(64))
    dst_ip = db.Column(db.String(64))
    meta = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MouseSession(db.Model):
    __tablename__ = "mouse_sessions"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(120), index=True)
    user_agent = db.Column(db.String(512))
    src_ip = db.Column(db.String(128))
    events = db.Column(db.JSON, nullable=False)  
    saved_at = db.Column(db.DateTime, default=datetime.utcnow)
    predict_label = db.Column(db.String(32), nullable=True)
    predict_confidence = db.Column(db.Float, nullable=True)

class Prediction(db.Model):
    __tablename__ = "predictions"
    id = db.Column(db.Integer, primary_key=True)
    model = db.Column(db.String(64)) 
    input_meta = db.Column(db.JSON)
    output = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)