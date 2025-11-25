# backend/db.py

import os
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional, List
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, create_engine, Boolean, Float, ForeignKey, BigInteger, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.types import JSON as SA_JSON, TypeDecorator
from sqlalchemy import Enum as SA_Enum
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("ai_ml_cyberdefense.db")
logger.setLevel(logging.INFO)

Base = declarative_base()
DB_SESSION = None

class JSONText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value, default=str)
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return json.loads(value)
        except Exception:
            return value

def json_type_for_engine(engine):
    try:
        dialect_name = engine.dialect.name.lower()
    except Exception:
        dialect_name = ""
    if dialect_name in ("mysql", "mariadb", "postgresql"):
        return SA_JSON
    return JSONText


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)  

    email = Column(String(255), nullable=True)
    role = Column(String(32), nullable=False, default="user")
    created_at = Column(DateTime, default=datetime.utcnow)

class MouseSession(Base):
    __tablename__ = "mouse_raw"
    id = Column(BigInteger, primary_key=True)
    session_id = Column(String(200), index=True, nullable=False)
    events = Column(Text, nullable=False)  
    meta = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(BigInteger, primary_key=True)
    atype = Column("model", String(128), index=True, nullable=False)
    score = Column("prob", Float, nullable=False)
    label = Column(String(64), nullable=True)
    src_ip = Column(String(45), nullable=True)
    dst_ip = Column(String(45), nullable=True)
    meta = Column("meta", Text, nullable=True)
    handled = Column("processed", Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        """Convenience helper to return a serializable dict."""
        return {
            "id": self.id,
            "atype": self.atype,
            "score": self.score,
            "label": self.label,
            "src_ip": self.src_ip,
            "dst_ip": self.dst_ip,
            "meta": _text_to_json(self.meta),
            "handled": bool(self.handled),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

class TrafficLog(Base):
    __tablename__ = "traffic_logs"
    id = Column(BigInteger, primary_key=True)
    features = Column(Text, nullable=False)   
    prob = Column(Float, nullable=True)
    label = Column(String(32), nullable=True)
    predicted_label = Column(String(32), nullable=True)
    src_ip = Column(String(45), nullable=True)
    dst_ip = Column(String(45), nullable=True)
    src_port = Column(Integer, nullable=True)
    dst_port = Column(Integer, nullable=True)
    proto = Column(String(16), nullable=True)
    meta = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# Map to JSON-style mouse dynamics table: 'mouse_dynamics'
class MouseDynamics(Base):
    __tablename__ = "mouse_dynamics"
    id = Column(BigInteger, primary_key=True)
    session_id = Column(String(128), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    features = Column(Text, nullable=False)    
    raw_events = Column(Text, nullable=True)   
    label = Column(String(16), nullable=False, default="unknown")
    predicted_label = Column(String(32), nullable=True)
    model = Column(String(64), nullable=True)
    score = Column(Float, nullable=True)
    meta = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# Detailed numeric summary table
class MouseDynamicsSummary(Base):
    __tablename__ = "mouse_dynamics_summary"
    id = Column(BigInteger, primary_key=True)
    session_id = Column(String(128), nullable=False, index=True)
    page = Column(String(255), nullable=True)
    ts = Column(BigInteger, nullable=False, index=True)  
    count = Column(Integer, nullable=True)
    avg_velocity = Column(Float, nullable=True)
    median_velocity = Column(Float, nullable=True)
    max_velocity = Column(Float, nullable=True)
    avg_acc = Column(Float, nullable=True)
    max_acc = Column(Float, nullable=True)
    std_acc = Column(Float, nullable=True)
    curvature_mean = Column(Float, nullable=True)
    curvature_std = Column(Float, nullable=True)
    pause_count = Column(Integer, nullable=True)
    longest_pause = Column(Integer, nullable=True)
    pct_pause_time = Column(Float, nullable=True)
    path_length = Column(Float, nullable=True)
    euclidean_distance = Column(Float, nullable=True)
    tortuosity = Column(Float, nullable=True)
    smoothness_index = Column(Float, nullable=True)
    mean_angle = Column(Float, nullable=True)
    angle_std = Column(Float, nullable=True)
    click_count = Column(Integer, nullable=True)
    avg_dwell_before_click = Column(Float, nullable=True)
    avg_time_between_clicks = Column(Float, nullable=True)
    click_speed = Column(Float, nullable=True)
    meta = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

from datetime import timedelta

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id = Column(Integer, primary_key=True)
    jti = Column(String(128), unique=True, index=True, nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    meta = Column(Text, nullable=True)

def store_refresh_jti(jti: str, expires_at: Optional[datetime] = None, meta: Optional[Dict] = None) -> None:

    session = get_db_session()
    try:
        existing = session.query(RefreshToken).filter(RefreshToken.jti == jti).first()
        if existing:
            existing.revoked = False
            existing.expires_at = expires_at
            existing.meta = _json_to_text(meta)
        else:
            rt = RefreshToken(jti=jti, revoked=False, expires_at=expires_at, meta=_json_to_text(meta))
            session.add(rt)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.exception("store_refresh_jti failed: %s", e)
        raise
    finally:
        session.close()

def revoke_refresh_jti(jti: str) -> None:
    session = get_db_session()
    try:
        rt = session.query(RefreshToken).filter(RefreshToken.jti == jti).first()
        if rt:
            rt.revoked = True
        else:
            rt = RefreshToken(jti=jti, revoked=True, created_at=datetime.utcnow())
            session.add(rt)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.exception("revoke_refresh_jti failed: %s", e)
        raise
    finally:
        session.close()

def is_refresh_revoked(jti: str) -> bool:

    session = get_db_session()
    try:
        rt = session.query(RefreshToken).filter(RefreshToken.jti == jti).first()
        if not rt:
            return False
        
        if rt.revoked:
            return True
        if rt.expires_at and isinstance(rt.expires_at, datetime) and rt.expires_at < datetime.utcnow():
            return True
        return False
    except Exception as e:
        logger.exception("is_refresh_revoked query failed: %s", e)
    
        return True
    finally:
        session.close()


def get_database_url() -> str:
    
   
    url = os.environ.get("DATABASE_URL", None)
    if url:
        return url

    # 2) try individual DB env vars (MySQL)
    db_user = os.environ.get("DATABASE_USER") or os.environ.get("MYSQL_USER")
    db_pass = os.environ.get("DATABASE_PASSWORD") or os.environ.get("MYSQL_PASSWORD")
    db_host = os.environ.get("DATABASE_HOST") or os.environ.get("MYSQL_HOST")
    db_port = os.environ.get("DATABASE_PORT") or os.environ.get("MYSQL_PORT") or "3306"
    db_name = os.environ.get("DATABASE_NAME") or os.environ.get("MYSQL_DATABASE")

    if db_user and db_pass and db_host and db_name:
        user_esc = db_user
        pass_esc = db_pass
        host = db_host
        port = db_port
        name = db_name
        return f"mysql+pymysql://{user_esc}:{pass_esc}@{host}:{port}/{name}?charset=utf8mb4"

    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    processed = os.path.join(ROOT, "data", "processed")
    os.makedirs(processed, exist_ok=True)
    sqlite_path = os.path.join(processed, "app.db")
    return f"sqlite:///{sqlite_path}"

def init_db(echo: bool = False):

    global DB_SESSION
    database_url = get_database_url()
    safe_url = database_url
    try:
        if "@" in database_url and "://" in database_url:
            proto, rest = database_url.split("://", 1)
            if "@" in rest:
                creds, hostpart = rest.split("@", 1)
                # mask password if present
                if ":" in creds:
                    user, pwd = creds.split(":", 1)
                    safe_url = f"{proto}://{user}:***@{hostpart}"
    except Exception:
        safe_url = "<hidden>"

    logger.info("Using database URL: %s", safe_url)
    try:
        engine = create_engine(database_url, echo=echo, pool_pre_ping=True)
    except Exception as e:
        logger.exception("Failed to create engine: %s", e)
        raise

    
    Base.metadata.create_all(engine)
    DB_SESSION = sessionmaker(bind=engine)
    return DB_SESSION


if DB_SESSION is None:
    try:
        init_db(echo=False)
    except Exception as e:
        logger.warning("DB initialization failed at import time: %s", e)


def get_db_session():
    
    global DB_SESSION
    if DB_SESSION is None:
        init_db()
    return DB_SESSION()

def _json_to_text(x: Optional[Any]) -> Optional[str]:
    if x is None:
        return None
    if isinstance(x, str):
        return x
    try:
        return json.dumps(x, default=str)
    except Exception:
        return str(x)

def _text_to_json(x: Optional[str]) -> Optional[Any]:
    if x is None:
        return None
    try:
        return json.loads(x)
    except Exception:
        return x

def insert_alert(atype: str, score: float, label: str, src_ip: Optional[str] = None,
                 dst_ip: Optional[str] = None, meta: Optional[Dict] = None) -> Dict:
   
    session = get_db_session()
    try:
        a = Alert(
            atype=str(atype),
            score=float(score),
            label=str(label),
            src_ip=src_ip,
            dst_ip=dst_ip,
            meta=_json_to_text(meta)
        )
        session.add(a)
        session.commit()
        session.refresh(a)
        out = {
            "id": a.id,
            "atype": a.atype,
            "score": a.score,
            "label": a.label,
            "src_ip": a.src_ip,
            "dst_ip": a.dst_ip,
            "meta": _text_to_json(a.meta),
            "created_at": a.created_at.isoformat()
        }
        logger.debug("Inserted alert: %s", out)
        return out
    except SQLAlchemyError as e:
        session.rollback()
        logger.exception("insert_alert SQL error: %s", e)
        raise
    finally:
        session.close()

def save_mouse(session_id: str, events: List[Dict], meta: Optional[Dict] = None) -> Dict:
    session = get_db_session()
    try:
        ms = MouseSession(
            session_id=str(session_id),
            events=_json_to_text(events),
            meta=_json_to_text(meta)
        )
        session.add(ms)
        session.commit()
        session.refresh(ms)
        out = {
            "id": ms.id,
            "session_id": ms.session_id,
            "created_at": ms.created_at.isoformat()
        }
        logger.debug("Saved mouse session: %s", out)
        return out
    except SQLAlchemyError as e:
        session.rollback()
        logger.exception("save_mouse SQL error: %s", e)
        raise
    finally:
        session.close()

def save_mouse_summary(summary: Dict) -> Dict:
    session = get_db_session()
    try:
        m = MouseDynamicsSummary(
            session_id=str(summary.get("session_id")),
            page=summary.get("page"),
            ts=int(summary.get("ts", int(time.time()*1000))),
            count=summary.get("count"),
            avg_velocity=summary.get("avg_velocity"),
            median_velocity=summary.get("median_velocity"),
            max_velocity=summary.get("max_velocity"),
            avg_acc=summary.get("avg_acc"),
            max_acc=summary.get("max_acc"),
            std_acc=summary.get("std_acc"),
            curvature_mean=summary.get("curvature_mean"),
            curvature_std=summary.get("curvature_std"),
            pause_count=summary.get("pause_count"),
            longest_pause=summary.get("longest_pause"),
            pct_pause_time=summary.get("pct_pause_time"),
            path_length=summary.get("path_length"),
            euclidean_distance=summary.get("euclidean_distance"),
            tortuosity=summary.get("tortuosity"),
            smoothness_index=summary.get("smoothness_index"),
            mean_angle=summary.get("mean_angle"),
            angle_std=summary.get("angle_std"),
            click_count=summary.get("click_count"),
            avg_dwell_before_click=summary.get("avg_dwell_before_click"),
            avg_time_between_clicks=summary.get("avg_time_between_clicks"),
            click_speed=summary.get("click_speed"),
            meta=_json_to_text(summary.get("meta"))
        )
        session.add(m)
        session.commit()
        session.refresh(m)
        out = {"id": m.id, "session_id": m.session_id, "created_at": m.created_at.isoformat()}
        logger.debug("Saved mouse summary: %s", out)
        return out
    except SQLAlchemyError as e:
        session.rollback()
        logger.exception("save_mouse_summary SQL error: %s", e)
        raise
    finally:
        session.close()


def get_latest_alerts(limit: int = 100) -> List[Dict]:
    """
    Return latest alerts ordered by created_at desc, limited by `limit`.
    """
    session = get_db_session()
    try:
        rows = session.query(Alert).order_by(Alert.created_at.desc()).limit(limit).all()
        out = []
        for r in rows:
            out.append({
                "id": r.id,
                "atype": r.atype,
                "score": r.score,
                "label": r.label,
                "src_ip": r.src_ip,
                "dst_ip": r.dst_ip,
                "meta": _text_to_json(r.meta),
                "created_at": r.created_at.isoformat(),
                "handled": bool(r.handled)
            })
        return out
    except SQLAlchemyError as e:
        logger.exception("get_latest_alerts SQL error: %s", e)
        raise
    finally:
        session.close()


def get_alert_by_id(aid: int) -> Optional[Dict]:
    session = get_db_session()
    try:
        r = session.query(Alert).filter(Alert.id == aid).first()
        if r is None:
            return None
        return {
            "id": r.id,
            "atype": r.atype,
            "score": r.score,
            "label": r.label,
            "meta": _text_to_json(r.meta),
            "created_at": r.created_at.isoformat()
        }
    finally:
        session.close()

def mark_alert_handled(aid: int):
    session = get_db_session()
    try:
        r = session.query(Alert).filter(Alert.id == aid).first()
        if not r:
            return False
        r.handled = True
        session.commit()
        return True
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()


def create_tables(echo: bool = False):
    """
    Explicitly (re)create tables. Use with caution in production.
    """
    database_url = get_database_url()
    engine = create_engine(database_url, echo=echo, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    logger.info("Created/verified tables on %s", database_url)

if __name__ == "__main__":
    create_tables()
    print("Tables ensured.")
    a = insert_alert("test_alert", 0.42, "test", src_ip="127.0.0.1", meta={"note": "hello"})
    print("Inserted alert:", a)
    s = save_mouse("test_session_1", [{"x": 10, "y": 20, "t": 0}, {"x": 11, "y": 21, "t": 10}], meta={"ua": "pytest"})
    print("Saved mouse:", s)
    summary_example = {"session_id": "test_session_1", "ts": int(time.time()*1000), "count": 2, "avg_velocity": 12.3}
    print("Saved summary:", save_mouse_summary(summary_example))
    print("Latest alerts:", get_latest_alerts(10))