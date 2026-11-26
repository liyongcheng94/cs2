"""设置读写：secret 键 Fernet 加密落库；对外列表脱敏、detail 仅服务端使用。"""
from __future__ import annotations

from sqlmodel import Session, select

from ..models import Setting, utcnow
from . import crypto

SECRET_KEYS = {"wanmei.access_token", "bili.sessdata", "mindvault.password", "ai.api_key"}

DEFAULTS: dict[str, str] = {
    "mv.base_url": "http://127.0.0.1:8001",
    "ai.provider": "deepseek",
}


def get_value(session: Session, key: str) -> str | None:
    row = session.get(Setting, key)
    if row is None:
        return DEFAULTS.get(key)
    if row.is_secret:
        return crypto.decrypt(row.value_enc)
    return row.value_enc


def set_value(session: Session, key: str, value: str) -> None:
    is_secret = key in SECRET_KEYS
    stored = crypto.encrypt(value) if is_secret else value
    row = session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value_enc=stored, is_secret=is_secret)
    else:
        row.value_enc = stored
        row.is_secret = is_secret
        row.updated_at = utcnow()
    session.add(row)
    session.commit()


def get_all_masked(session: Session) -> dict[str, str]:
    rows = session.exec(select(Setting)).all()
    out: dict[str, str] = {}
    for key in set(DEFAULTS) | {r.key for r in rows}:
        val = get_value(session, key)
        if key in SECRET_KEYS and val:
            val = "****" + val[-2:] if len(val) > 2 else "****"
        out[key] = val or ""
    return out


def get_detail(session: Session) -> dict[str, str]:
    """detail 亦脱敏：机密键任何 API 响应都不得出现明文。"""
    rows = session.exec(select(Setting)).all()
    out = dict(DEFAULTS)
    for key in {r.key for r in rows}:
        val = get_value(session, key) or ""
        if key in SECRET_KEYS and val:
            val = "****" + val[-2:] if len(val) > 2 else "****"
        out[key] = val
    return out
