"""B站数据管线（阶段 3）：WBI 签名检索 / 字幕获取（SESSDATA）/ 风控软着陆。

- 检索走自研 WBI 签名（MindVault bili_feed 同款公开算法），登录态 Cookie 必带。
- 字幕仅走字幕路线：无字幕标 no_subtitle 跳过（评审：ASR 首版砍掉）。
- 风控软着陆：-412/-352 等码 → BiliRiskError，任务层暂停对应关键词 ≥1h。
- 限速 1s/视频由调用方（任务）控制。
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
from typing import Any

import httpx
from loguru import logger

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
SEARCH_URL = "https://api.bilibili.com/x/web-interface/wbi/search/type"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]

RISK_CODES = {-412, -352, 10031, 12051, 12015}

_wbi_cache: tuple[float, str, str] = (0.0, "", "")


class BiliError(Exception):
    """B站普通错误。"""


class BiliRiskError(Exception):
    """风控拦截——任务层必须暂停 ≥1h（对应关键词/UP），严禁盲目重试。"""


def _get_mixin_key(mixed: str) -> str:
    return "".join(mixed[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def sign_wbi(params: dict, img_key: str, sub_key: str, wts: int | None = None) -> dict:
    """wbi 签名：附 wts + w_rid（md5）。同参数同刻签名确定。"""
    mixed = _get_mixin_key(img_key + sub_key)
    wts = int(time.time()) if wts is None else int(wts)
    cleaned = {k: "".join(ch for ch in str(v) if ch not in "!'()*") for k, v in params.items()}
    cleaned["wts"] = wts
    query = urllib.parse.urlencode(sorted(cleaned.items()))
    w_rid = hashlib.md5((query + mixed).encode()).hexdigest()
    return {**cleaned, "w_rid": w_rid}


def _search_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=15, follow_redirects=True)


async def _wbi_keys(client: httpx.AsyncClient, cookie: str = "") -> tuple[str, str]:
    global _wbi_cache
    now = time.time()
    if now - _wbi_cache[0] < 3600 and _wbi_cache[1]:
        return _wbi_cache[1], _wbi_cache[2]
    headers = {**HEADERS, "Cookie": cookie} if cookie else HEADERS
    resp = await client.get(NAV_URL, headers=headers)
    resp.raise_for_status()
    wbi = (resp.json().get("data") or {}).get("wbi_img") or {}
    img_url, sub_url = wbi.get("img_url") or "", wbi.get("sub_url") or ""
    if not img_url or not sub_url:
        raise BiliError("B站 nav 未返回 wbi key")
    img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
    _wbi_cache = (now, img_key, sub_key)
    return img_key, sub_key


async def search_videos(keyword: str, sessdata: str = "", page: int = 1) -> list[dict[str, Any]]:
    """WBI 检索视频：返回 [{bvid,title,author,pubdate}]（标题剥 <em> 标记）。"""
    cookie = f"SESSDATA={sessdata};" if sessdata else ""
    async with _search_client() as client:
        img_key, sub_key = await _wbi_keys(client, cookie)
        signed = sign_wbi({"keyword": keyword, "page": page, "search_type": "video"}, img_key, sub_key)
        headers = {**HEADERS, "Cookie": cookie} if cookie else HEADERS
        resp = await client.get(SEARCH_URL, params=signed, headers=headers)
        data = resp.json()
        if data.get("code") in RISK_CODES:
            raise BiliRiskError(f"B站风控 code={data.get('code')}：{data.get('message')}")
        if data.get("code") != 0:
            raise BiliError(f"B站检索错误 code={data.get('code')}：{data.get('message')}")
        rows = (data.get("data") or {}).get("result") or []
        out = []
        for r in rows:
            title = (r.get("title") or "").replace('<em class="keyword">', "").replace("</em>", "")
            out.append({
                "bvid": r.get("bvid"),
                "title": title,
                "author": r.get("author"),
                "pubdate": r.get("pubdate"),
            })
        logger.info(f"[B站检索] keyword={keyword!r} page={page} 命中={len(out)}")
        return out


async def resolve_bvid(url_or_bvid: str) -> str:
    """b23.tv 短链 / 完整视频链接 / 裸 BV → 纯 BV 号（跟随重定向提取）。"""
    s = (url_or_bvid or "").strip()
    m = re.search(r"(BV[0-9A-Za-z]{10})", s)
    if m:
        return m.group(1)
    if "b23.tv" in s or "bilibili.com" in s:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers=HEADERS) as client:
            resp = await client.get(s if s.startswith("http") else f"https://{s}")
        loc = resp.headers.get("location", "")
        m = re.search(r"(BV[0-9A-Za-z]{10})", loc)
        if m:
            return m.group(1)
        raise BiliError(f"短链解析失败：{loc[:120] or f'HTTP {resp.status_code}'}")
    raise BiliError(f"无法从输入解析 BV 号：{s[:80]}")


async def fetch_video_meta(bvid: str, sessdata: str = "") -> dict[str, Any] | None:
    """取视频元数据（封面/时长/UP mid）；失败返回 None 不阻断学习主链路。

    grill-me 决策 C（2026-11-23）：学习时顺手抓，raw 存 {cover, duration, owner_mid}
    供前端卡片墙 <img referrerPolicy="no-referrer"> 直显（B站防盗链：无 Referer 200）。
    """
    try:
        from bilibili_api import Credential
        from bilibili_api import video as bili_video_mod

        cred = Credential(sessdata=sessdata) if sessdata else Credential()
        v = bili_video_mod.Video(bvid=bvid, credential=cred)
        info = await v.get_info()
        owner = info.get("owner") or {}
        return {
            "cover": info.get("pic") or "",
            "duration": info.get("duration") or 0,
            "owner_mid": owner.get("mid"),
        }
    except Exception as exc:  # noqa: BLE001 — 元数据是锦上添花，失败不阻断学习
        logger.warning(f"[B站元数据] bvid={bvid} 获取失败（忽略）：{type(exc).__name__}: {str(exc)[:100]}")
        return None


async def fetch_subtitle(bvid: str, sessdata: str) -> str | None:
    """取字幕纯文本（zh-CN > ai-zh > 首轨）；无字幕返回 None（调用方标 no_subtitle）。"""
    from bilibili_api import Credential
    from bilibili_api import video as bili_video_mod

    cred = Credential(sessdata=sessdata)
    v = bili_video_mod.Video(bvid=bvid, credential=cred)
    info = await v.get_info()
    cid = info.get("cid")
    sub = await v.get_subtitle(cid=cid)
    subs = sub.get("subtitles") or []
    if not subs:
        return None
    pick = next((s for s in subs if s.get("lan") == "zh-CN"), None) or next(
        (s for s in subs if s.get("lan") == "ai-zh"), subs[0]
    )
    sub_url: str = pick.get("subtitle_url") or ""
    if sub_url.startswith("//"):
        sub_url = "https:" + sub_url
    if not sub_url:
        return None
    resp = httpx.get(sub_url, headers=HEADERS, timeout=15)
    body = resp.json()
    lines = [item.get("content", "") for item in body.get("body") or []]
    text = "\n".join(x for x in lines if x)
    logger.info(f"[B站字幕] bvid={bvid} lan={pick.get('lan')} 行数={len(lines)}")
    return text or None


async def search_user_videos(mid: int, sessdata: str, limit: int = 5) -> list[dict[str, Any]]:
    """UP 主最新投稿（bilibili-api user.User.get_videos，按发布时间倒序取 limit 条）。"""
    from bilibili_api import Credential
    from bilibili_api import user as bili_user_mod

    cred = Credential(sessdata=sessdata)
    u = bili_user_mod.User(uid=mid, credential=cred)
    res = await u.get_videos(pn=1, ps=max(limit, 5))
    rows = (res.get("list") or {}).get("vlist") or []
    out = [
        {"bvid": r.get("bvid"), "title": r.get("title"), "author": r.get("author"), "pubdate": r.get("created")}
        for r in rows[:limit]
    ]
    logger.info(f"[B站UP] mid={mid} 取 {len(out)} 条最新投稿")
    return out
