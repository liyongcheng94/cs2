"""凭证对称加密：Fernet，密钥来自环境口令或 data/secret.key（均不入 git）。"""
from __future__ import annotations

import base64
import functools
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from ..config import get_data_dir


@functools.lru_cache(maxsize=8)
def _fernet_for(material: bytes) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(material).digest())
    return Fernet(key)


def _material() -> bytes:
    env = os.environ.get("CS2HQ_SECRET_KEY")
    if env:
        return env.encode()
    path = get_data_dir() / "secret.key"
    if not path.exists():
        path.write_bytes(base64.urlsafe_b64encode(os.urandom(32)))
    return path.read_bytes()


def _fernet() -> Fernet:
    return _fernet_for(_material())


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # pragma: no cover - 防御分支
        raise ValueError("解密失败：secret.key/口令与加密时不一致") from exc
