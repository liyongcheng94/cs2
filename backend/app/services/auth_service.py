"""账号服务（Phase 2）：pbkdf2 密码哈希 + PyJWT HS256 token（httpOnly cookie）。

决策记录（2026-11-26 grill）：用户名+密码；公网已有 Cloudflare Access 挡第一道门，
应用层只做身份区分与数据隔离；首个注册用户 is_admin=True。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from sqlmodel import Session, select

from ..models import User, utcnow

COOKIE_NAME = "cs2hq_token"
_TOKEN_TTL_DAYS = 30
_PBKDF2_ITERS = 120_000


def _secret() -> str:
    return os.environ.get("CS2HQ_SECRET_KEY") or "cs2hq-dev-secret-do-not-use-in-prod"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERS)
    return f"pbkdf2${_PBKDF2_ITERS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_b64, dk_b64 = stored.split("$")
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt_b64), int(iters)
        )
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except (ValueError, TypeError):
        return False


def create_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    # 不签 iat/nbf：WSL2 宿主时钟会回跳（实测回跳 >10s），iat 在未来会触发
    # ImmatureSignatureError 导致随机 401；过期仅靠 exp（30d）判定。
    return jwt.encode(
        {"sub": str(user_id), "exp": now + timedelta(days=_TOKEN_TTL_DAYS)},
        _secret(),
        algorithm="HS256",
    )


def decode_user_id(token: str) -> int | None:
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def get_by_username(session: Session, username: str) -> User | None:
    return session.exec(select(User).where(User.username == username)).first()


def get_by_id(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def create_user(session: Session, username: str, password: str, display_name: str = "") -> User:
    """首个注册用户自动 is_admin；用户名唯一。"""
    is_first = session.exec(select(User)).first() is None
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name or username,
        is_admin=is_first,
        created_at=utcnow(),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
