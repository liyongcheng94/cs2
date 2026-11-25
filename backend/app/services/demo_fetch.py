"""demo_fetch：完美平台 demo 纯 API 直下（签名 URL + X-PWA 头）→ 解压缓存 → 串联 demo_analyze。

签名契约（社区逆向 cs_demo_pwa_signer）：
- URL: https://pwaweblogin.wmpvp.com/csgo/demo/{match_id}_0.dem
       ?a=20000&r={randnum}&s={sig}&t={ts}&access_token=..&cup_id=0&match_id=..
- s = sign_demo_request(randnum, ts, "access_token=..&cup_id=0&match_id=..")
- X-PWA-Signature = build_x_pwa_signature(steam_id, ts, 公网IP)（AES-128-CBC）
- 头必须带 Referer: https://client.wmpvp.com + 完美 Electron UA + 多形态 steamid 头

响应语义：200 octet-stream = zip（内含 .dem）；JSON 体 = demo 过期/不存在；
401/403 = WanmeiAuthError（熔断，绝不重试）。
"""
from __future__ import annotations

import io
import random
import time
import zipfile
from typing import Any, Callable

import httpx
from sqlmodel import Session

from ..config import get_data_dir
from ..models import Task
from .wanmei import WanmeiAuthError

DEMO_URL_TMPL = "https://pwaweblogin.wmpvp.com/csgo/demo/{num}_0.dem"
PWA_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "perfectworldarena/1.0.26051411 Chrome/80.0.3987.163 Electron/8.5.5 Safari/537.36"
)
_PUBLIC_IP_URLS = ["https://api.ipify.org/", "https://ifconfig.me/ip"]
_DOWNLOAD_TIMEOUT_S = 600.0


class DemoUnavailableError(RuntimeError):
    """完美服务器拒绝下发 demo（过期/签名错/不存在）。"""


# 可注入桩（测试用）：签名器、HTTP 传输层、公网 IP 缓存
_signer: Any = None
_transport: httpx.AsyncBaseTransport | None = None
_public_ip_cache: str | None = None


def _load_signer() -> Any:
    global _signer
    if _signer is None:
        import cs_demo_pwa_signer  # vendored wheel（backend/vendor）

        _signer = cs_demo_pwa_signer
    return _signer


def _build_demo_url(signer: Any, num: str, token: str) -> str:
    randnum = str(random.randint(10000, 99999))
    ts = str(int(time.time()))
    data = f"access_token={token}&cup_id=0&match_id={num}"
    sig = signer.sign_demo_request(randnum, ts, data)
    if isinstance(sig, bytes):
        sig = sig.decode()
    return (
        f"{DEMO_URL_TMPL.format(num=num)}"
        f"?a=20000&r={randnum}&s={sig}&t={ts}&access_token={token}&cup_id=0&match_id={num}"
    )


def _build_headers(signer: Any, steam_id: str, ip: str) -> dict[str, str]:
    ts = int(time.time())
    xp = signer.build_x_pwa_signature(steam_id, ts, ip)
    if isinstance(xp, bytes):
        xp = xp.decode()
    return {
        "User-Agent": PWA_UA,
        "Referer": "https://client.wmpvp.com",
        "X-PWA-Signature": xp,
        "X-PWA-Timestamp": str(ts),
        "X-PWA-SteamId": steam_id,
        "X-Pwa-SteamId": steam_id,
        "x-pwa-steamid": steam_id,
        "pwasteamid": steam_id,
    }


async def _get_public_ip(client: httpx.AsyncClient) -> str:
    global _public_ip_cache
    if _public_ip_cache:
        return _public_ip_cache
    last: Exception | None = None
    for url in _PUBLIC_IP_URLS:
        try:
            resp = await client.get(url)
            ip = resp.text.strip()
            if ip:
                _public_ip_cache = ip
                return ip
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise DemoUnavailableError(f"获取公网出口 IP 失败（完美签名必需）：{last}")


def _looks_like_json(resp: httpx.Response, body: bytes) -> bool:
    ctype = resp.headers.get("Content-Type", "")
    return "json" in ctype or "text" in ctype or body[:1] in (b"{", b"[")


async def _download_demo(num: str, token: str, steam_id: str) -> bytes:
    signer = _load_signer()
    async with httpx.AsyncClient(transport=_transport, timeout=_DOWNLOAD_TIMEOUT_S, follow_redirects=True) as client:
        ip = await _get_public_ip(client)
        url = _build_demo_url(signer, num, token)
        headers = _build_headers(signer, steam_id, ip)
        resp = await client.get(url, headers=headers)
    if resp.status_code in (401, 403):
        raise WanmeiAuthError(f"完美 demo 接口鉴权失败（HTTP {resp.status_code}）")
    body = resp.content
    if resp.status_code != 200 or _looks_like_json(resp, body):
        raise DemoUnavailableError("demo 已过期或不存在（完美服务器拒绝下发）")
    return body


def _extract_dem(zip_bytes: bytes, num: str, cache_dir) -> Any:
    """从 zip 提取 .dem 到缓存目录，返回 dem 路径。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        members = [n for n in z.namelist() if n.endswith(".dem")]
        if not members:
            raise DemoUnavailableError("zip 内没有 .dem 文件（响应异常）")
        target = cache_dir / f"{num}_0.dem"
        target.write_bytes(z.read(members[0]))
        return target


async def demo_fetch_handler(task: Task, session_factory_fn: Callable[[], Session]) -> dict:
    """下载并分析一场完美 demo：PVP@ 场次 → 签名直下 → demo_analyze 全链路。"""
    from . import demo_analyze as da
    from .settings_service import get_value

    match_id = str((task.payload or {}).get("match_id", ""))
    if not match_id.startswith("PVP@"):
        raise ValueError(f"demo_fetch 仅支持完美平台场次（PVP@ 前缀），收到：{match_id}")
    num = match_id[4:]

    from sqlmodel import select

    from ..models import Match

    with session_factory_fn() as session:
        if session.exec(select(Match).where(Match.match_id == match_id)).first() is None:
            raise ValueError(f"对局 {match_id} 不在本地库（先同步战绩）")

    cache_dir = get_data_dir() / "demos"
    dem_path = cache_dir / f"{num}_0.dem"
    downloaded = False
    if not dem_path.exists():
        token = get_value(session, "wanmei.access_token")
        if not token:
            raise WanmeiAuthError("未配置完美平台 access_token")
        steam_id = get_value(session, "wanmei.steam_id") or ""
        zip_bytes = await _download_demo(num, token, steam_id)
        dem_path = _extract_dem(zip_bytes, num, cache_dir)
        downloaded = True
        with session_factory_fn() as session:
            row = session.exec(select(Match).where(Match.match_id == match_id)).first()
            if row is not None:
                row.demo_status = "downloaded"
                session.add(row)
                session.commit()

    result = await da.demo_analyze_handler(task, session_factory_fn)
    return {"downloaded": downloaded, "dem": str(dem_path), **result}


def register() -> None:
    from . import task_manager

    task_manager.HANDLERS["demo_fetch"] = demo_fetch_handler
