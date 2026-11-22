"""完美平台服务契约：短信登录三步 + 对局拉取 + 401/403 熔断（全部走 MockTransport，不发真实短信）。"""
import json

import httpx
import pytest

from app.services.wanmei import (
    PassportClient,
    WanmeiAPI,
    WanmeiAuthError,
    WanmeiError,
)

PASSPORT_HEADERS = {"platform": "APP", "appversion": "3.1.0"}


@pytest.mark.anyio
async def test_captcha_init_returns_ticket():
    """
    Given passport initcaptcha 可用
    When  captcha_init()
    Then  返回 capTicket（且请求带 platform/appversion 头）
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["platform"] = request.headers.get("platform")
        return httpx.Response(
            200, json={"code": 0, "capTicket": "tkt-1", "url": "https://c.example/captcha.html"}
        )

    c = PassportClient(transport=httpx.MockTransport(handler))
    out = await c.captcha_init()
    assert out["capTicket"] == "tkt-1"
    assert seen["path"] == "/initcaptcha"
    assert seen["platform"] == "APP"


@pytest.mark.anyio
async def test_send_code_success_and_failure():
    """
    Given 用户完成滑块拿到 secCode/capTicket
    When  send_code(mobilePhone, secCode, capTicket)
    Then  code=0 表示短信已发；code!=0 抛 WanmeiError 且带 description
    """
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["mobilePhone"])
        if request.url.params["secCode"] == "good":
            return httpx.Response(200, json={"code": 0, "description": "Success"})
        return httpx.Response(200, json={"code": 50002, "description": "验证码校验失败"})

    c = PassportClient(transport=httpx.MockTransport(handler))
    await c.send_code("13800138000", "good", "tkt-1")
    assert calls == ["13800138000"]

    with pytest.raises(WanmeiError, match="验证码校验失败"):
        await c.send_code("13800138000", "bad", "tkt-1")


@pytest.mark.anyio
async def test_sms_login_returns_token_and_steam_id():
    """
    Given 用户提交 6 位短信码
    When  sms_login(mobilePhone, securityCode)
    Then  返回 {token, steam_id, user_id}（appId=10，与 partner 门户一致）
    """

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["appId"] == 10
        return httpx.Response(
            200,
            json={
                "code": 0,
                "result": {
                    "loginResult": {
                        "accountInfo": {
                            "token": "tok-40chars",
                            "steamId": 76561198929200000,
                            "userId": 58072600,
                            "mobilePhone": "13800138000",
                        }
                    }
                },
            },
        )

    c = PassportClient(transport=httpx.MockTransport(handler))
    out = await c.sms_login("13800138000", "123456")
    assert out["token"] == "tok-40chars"
    assert out["steam_id"] == 76561198929200000


@pytest.mark.anyio
async def test_match_list_passes_token_headers_and_parses():
    """
    Given 已登录 token
    When  match_list(page=1)
    Then  POST api.wmpvp.com/api/csgo/home/match/list 带 token/platform/appversion 头，
          body 含 mySteamId/dataSource/page，返回对局列表原始结构
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("token")
        seen["platform"] = request.headers.get("platform")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "result": {"dataList": [{"matchId": "PVP@X1", "mapName": "de_dust2"}], "total": 1},
            },
        )

    api = WanmeiAPI(token="tok-1", steam_id="76561198929200000", transport=httpx.MockTransport(handler))
    out = await api.match_list(page=1, page_size=20)
    assert out["dataList"][0]["matchId"] == "PVP@X1"
    assert seen["token"] == "tok-1"
    assert seen["platform"] == "android"
    assert seen["body"]["mySteamId"] == "76561198929200000"
    assert seen["body"]["dataSource"] == 3


@pytest.mark.anyio
async def test_wanmei_401_breaks_to_auth_error():
    """
    Given token 失效（服务端回 401 或 code=10001 类鉴权失败）
    When  match_list
    Then  抛 WanmeiAuthError（任务层熔断为 NEED_AUTH，严禁后台重试）
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": 10002, "description": "token 失效"})

    api = WanmeiAPI(token="expired", steam_id="1", transport=httpx.MockTransport(handler))
    with pytest.raises(WanmeiAuthError):
        await api.match_list(page=1)


@pytest.mark.anyio
async def test_wanmei_network_error_wrapped():
    """
    Given api.wmpvp.com 不可达
    When  match_list
    Then  抛 WanmeiError（普通失败，允许下轮定时重试，与 AUTH 熔断区分）
    """
    api = WanmeiAPI(token="t", steam_id="1", transport=None)
    with pytest.raises(WanmeiError):
        await api.match_list(page=1)
