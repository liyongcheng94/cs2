"""完美平台（PWA）客户端。

- 登录链路（passport.pwesports.cn，与 partner 门户同款）：initcaptcha → 用户过 WanmeiCaptcha 滑块
  → securitycode 发短信 → account/login（appId=10）拿 token/steamId。
- 数据接口（api.wmpvp.com，手机 App 同款头）：match/list、pvp/detailStats。
- 熔断约定：401/403/鉴权失败码 → WanmeiAuthError（任务层熔断 NEED_AUTH，严禁后台重试）；
  其余网络/业务错误 → WanmeiError（允许定时任务下轮重试）。
"""
from __future__ import annotations

import httpx
from loguru import logger

PASSPORT_BASE = "https://passport.pwesports.cn"
API_BASE = "https://api.wmpvp.com"
PASSPORT_HEADERS = {"platform": "APP", "appversion": "3.1.0"}
API_HEADERS_BASE = {"platform": "android", "appversion": "3.5.4.172", "gameType": "1,2"}
LOGIN_APP_ID = 10  # partner 门户登录同款；token 与 steamId 1:1 绑定

AUTH_BROKEN_CODES = {10002, 401, 403}


class WanmeiError(Exception):
    """普通失败（网络/业务错误）——定时任务可下轮重试。"""


class WanmeiAuthError(Exception):
    """token 失效——必须熔断为 NEED_AUTH，严禁后台重试。"""


class _BaseClient:
    def __init__(self, base_url: str, headers: dict, transport: httpx.AsyncBaseTransport | None, timeout: float):
        self._http = httpx.AsyncClient(
            base_url=base_url, transport=transport, timeout=timeout, headers=headers
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, url: str, **kw) -> httpx.Response:
        verb = method.lower()
        try:
            resp = await getattr(self._http, verb)(url, **kw)
        except httpx.HTTPError as exc:
            raise WanmeiError(f"完美平台不可达：{exc}") from exc
        if resp.status_code in (401, 403):
            raise WanmeiAuthError(f"完美平台鉴权失败：HTTP {resp.status_code}")
        return resp

    @staticmethod
    def _parse_json(resp: httpx.Response) -> dict:
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise WanmeiError(f"完美平台返回非 JSON（HTTP {resp.status_code}）") from exc


class PassportClient(_BaseClient):
    """短信登录三步（不触碰验证码自动化：滑块永远由用户在 WanmeiCaptcha 里自己完成）。"""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 15.0):
        super().__init__(PASSPORT_BASE, PASSPORT_HEADERS, transport, timeout)

    async def _unwrap(self, resp: httpx.Response, *, auth_codes: set[int] | None = None) -> dict:
        data = self._parse_json(resp)
        code = data.get("code")
        if code == 0:
            return data
        if auth_codes and code in auth_codes:
            raise WanmeiAuthError(f"完美平台登录态失效：{data.get('description')}")
        raise WanmeiError(f"完美平台接口错误 code={code}：{data.get('description')}")

    async def captcha_init(self) -> dict:
        """初始化验证码：返回 {capTicket, url}。url 为 WanmeiCaptcha 需要的滑块页（前端加载组件用）。"""
        resp = await self._request("GET", "/initcaptcha")
        return await self._unwrap(resp)

    async def send_code(self, mobile_phone: str, sec_code: str, cap_ticket: str) -> None:
        """发送短信验证码（用户已过滑块）。成功即短信已发出。"""
        resp = await self._request(
            "GET",
            "/securitycode",
            params={"mobilePhone": mobile_phone, "secCode": sec_code, "capTicket": cap_ticket, "reason": 1},
        )
        await self._unwrap(resp)
        logger.info(f"[完美登录] 验证码已发送 mobile={mobile_phone[:3]}****")

    async def sms_login(self, mobile_phone: str, security_code: str) -> dict:
        """短信码登录：返回 {token, steam_id, user_id, mobile_phone}。"""
        resp = await self._request(
            "POST", "/account/login", json={"appId": LOGIN_APP_ID, "mobilePhone": mobile_phone, "securityCode": security_code}
        )
        data = await self._unwrap(resp)
        try:
            info = data["result"]["loginResult"]["accountInfo"]
        except (KeyError, TypeError) as exc:
            raise WanmeiError(f"登录响应结构异常：{str(data)[:200]}") from exc
        logger.info(f"[完美登录] 登录成功 steamId={info.get('steamId')}")
        return {
            "token": info["token"],
            "steam_id": info["steamId"],
            "user_id": info.get("userId"),
            "mobile_phone": info.get("mobilePhone") or mobile_phone,
        }


class WanmeiAPI(_BaseClient):
    """对局/统计数据接口（token 登录态）。"""

    # v1 详情端点使用 Electron 桌面客户端 UA + accesstoken 头（CS2UID 实测契约）
    V1_HEADERS_EXTRA = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "perfectworldarena/1.0.24060811   Chrome/80.0.3987.163 Electron/8.5.5 Safari/537.36"
        ),
        "accesstoken": "",  # __init__ 时填 token
    }
    V1_APPVERSION = "3.4.6.164"

    def __init__(self, token: str, steam_id: str, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 20.0):
        super().__init__(API_BASE, {**API_HEADERS_BASE, "token": token}, transport, timeout)
        self.steam_id = str(steam_id)
        self.v1_headers = {**self._http.headers, **self.V1_HEADERS_EXTRA, "accesstoken": token, "appversion": self.V1_APPVERSION}

    async def match_detail_v1(self, match_id: str) -> dict:
        """对局详情（/api/v1/csgo/match）：base 比分/上下半场 + players 全场 10 人详细数据。"""
        resp = await self._request(
            "POST",
            "/api/v1/csgo/match",
            headers=self.v1_headers,
            json={"matchId": match_id, "platform": "admin", "dataSource": 3},
        )
        return await self._unwrap_data(resp)

    async def _unwrap_data(self, resp: httpx.Response) -> dict:
        """兼容两种响应封装：新 {statusCode, data} 与文档旧 {code, result}。"""
        data = self._parse_json(resp)
        status = data.get("statusCode", data.get("code"))
        if status == 0:
            payload = data.get("data") if "data" in data else data.get("result")
            return payload if isinstance(payload, dict) else {}
        msg = data.get("errorMessage") or data.get("description") or ""
        if status in AUTH_BROKEN_CODES:
            raise WanmeiAuthError(f"完美平台 token 失效：{msg}")
        raise WanmeiError(f"完美平台接口错误 statusCode={status}：{msg}")

    async def match_list(self, page: int = 1, page_size: int = 20) -> dict:
        """对局列表（dataSource=3 为对战记录；按 csgoSeasonId=recent 取最近赛季）。"""
        resp = await self._request(
            "POST",
            "/api/csgo/home/match/list",
            json={
                "csgoSeasonId": "recent",
                "dataSource": 3,
                "mySteamId": self.steam_id,
                "toSteamId": self.steam_id,
                "page": page,
                "pageSize": page_size,
                "pvpType": -1,
            },
        )
        return await self._unwrap_data(resp)

    async def detail_stats(self, season_id: str = "recent") -> dict:
        """赛季个人统计（ADR/rating/pwRating/RWS/爆头率/首杀率/残局/雷达图等）。"""
        resp = await self._request(
            "POST",
            "/api/csgo/home/pvp/detailStats",
            json={"mySteamId": self.steam_id, "toSteamId": self.steam_id, "accessToken": "", "csgoSeasonId": season_id},
        )
        return await self._unwrap_data(resp)
