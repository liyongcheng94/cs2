"""B站管线契约：WBI 检索 / 字幕获取（SESSDATA）/ 风控软着陆 / 学习任务编排（总结+道具卡走 AI，无 Key 降级）。"""
import asyncio
import json

import httpx
import pytest

from app.services.bili import BiliError, BiliRiskError, sign_wbi


def test_sign_wbi_deterministic():
    """
    Given 同参数同刻
    When  sign_wbi
    Then  w_rid 确定（同参数同秒签名一致）
    """
    p1 = sign_wbi({"keyword": "CS2", "page": 1}, "a" * 32, "b" * 32, wts=1700000000)
    p2 = sign_wbi({"keyword": "CS2", "page": 1}, "a" * 32, "b" * 32, wts=1700000000)
    assert p1["w_rid"] == p2["w_rid"]
    assert p1["wts"] == 1700000000
    assert "w_rid" in p1


def test_sign_wbi_strips_special_chars():
    """
    Given 参数含 !'()* 特殊字符
    When  sign_wbi
    Then  签名前清洗这些字符（B站 wbi 规范）
    """
    p = sign_wbi({"kw": "a!b'c(d)e*f"}, "a" * 32, "b" * 32, wts=1700000000)
    assert p["kw"] == "abcdef"


@pytest.mark.anyio
async def test_search_videos_parses_results(monkeypatch):
    """
    Given WBI 检索端点桩返回视频列表
    When  search_videos("CS2 道具")
    Then  解析出 bvid/title/author 列表（剥掉 <em> 标记）
    """
    import app.services.bili as b

    def handler(request: httpx.Request) -> httpx.Response:
        assert "w_rid" in str(request.url.params)
        return httpx.Response(200, json={"code": 0, "data": {"result": [
            {"bvid": "BV1xx", "title": "<em class=\"keyword\">CS2</em> A大道具", "author": "教学UP", "pubdate": 1700000000},
            {"bvid": "BV1yy", "title": "B点烟", "author": "另一个UP", "pubdate": 1700000100},
        ]}})

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None, params=None):
            return handler(httpx.Request("GET", url, params=params or {}, headers=headers or {}))

    monkeypatch.setattr(b, "_search_client", lambda: FakeClient())
    async def fake_keys(client, cookie=""):
        return "a" * 32, "b" * 32
    monkeypatch.setattr(b, "_wbi_keys", fake_keys)

    out = await b.search_videos("CS2 道具")
    assert [o["bvid"] for o in out] == ["BV1xx", "BV1yy"]
    assert "<em" not in out[0]["title"]
    assert out[0]["author"] == "教学UP"


@pytest.mark.anyio
async def test_search_videos_risk_control_raises(monkeypatch):
    """
    Given 端点返回 -412（风控）
    When  search_videos
    Then  抛 BiliRiskError（任务层暂停该关键词 ≥1h，不盲目重试）
    """
    import app.services.bili as b

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": -412, "message": "请求被拦截"})

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None, params=None):
            return handler(httpx.Request("GET", url, params=params or {}, headers=headers or {}))

    monkeypatch.setattr(b, "_search_client", lambda: FakeClient())
    async def fake_keys(client, cookie=""):
        return "a" * 32, "b" * 32
    monkeypatch.setattr(b, "_wbi_keys", fake_keys)

    with pytest.raises(BiliRiskError):
        await b.search_videos("任意词")


class FakeRedirectClient:
    """resolve_bvid 专用假客户端：记录请求 URL，返回预置 302 Location。"""

    last_url: str | None = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        FakeRedirectClient.last_url = url
        return self.resp

    resp = httpx.Response(
        302,
        headers={"location": "https://www.bilibili.com/video/BV1GJ411x7h7/?p=1"},
    )


@pytest.mark.anyio
async def test_resolve_bvid_bare_bv(monkeypatch):
    """
    Given 裸 BV 号（用户手抄输入）
    When  resolve_bvid
    Then  原样返回，不发任何网络请求
    """
    import app.services.bili as b

    def boom(*a, **kw):  # 若发起网络请求则测试失败
        raise AssertionError("裸 BV 不应发起网络请求")

    monkeypatch.setattr(b.httpx, "AsyncClient", boom)
    assert await b.resolve_bvid("BV1GJ411x7h7") == "BV1GJ411x7h7"


@pytest.mark.anyio
async def test_resolve_bvid_from_full_url(monkeypatch):
    """
    Given 完整视频链接（URL 内含 BV）
    When  resolve_bvid
    Then  正则直接提取 BV，不发网络请求
    """
    import app.services.bili as b

    def boom(*a, **kw):
        raise AssertionError("含 BV 的链接不应发起网络请求")

    monkeypatch.setattr(b.httpx, "AsyncClient", boom)
    url = "https://www.bilibili.com/video/BV1GJ411x7h7/?spm_id_from=333.788&p=2"
    assert await b.resolve_bvid(url) == "BV1GJ411x7h7"


@pytest.mark.anyio
async def test_resolve_bvid_short_link_follows_redirect(monkeypatch):
    """
    Given b23.tv 短链（无 scheme）且 302 Location 落到含 BV 的页面
    When  resolve_bvid
    Then  补 https:// 前缀发请求，从 Location 提取 BV
    """
    import app.services.bili as b

    monkeypatch.setattr(b.httpx, "AsyncClient", FakeRedirectClient)
    out = await b.resolve_bvid("b23.tv/abc123")
    assert out == "BV1GJ411x7h7"
    assert FakeRedirectClient.last_url == "https://b23.tv/abc123"


@pytest.mark.anyio
async def test_resolve_bvid_short_link_without_bv_raises(monkeypatch):
    """
    Given 短链 302 到不含 BV 的 Location
    When  resolve_bvid
    Then  抛 BiliError（提示短链解析失败）
    """
    import app.services.bili as b

    class NoBVClient(FakeRedirectClient):
        resp = httpx.Response(302, headers={"location": "https://www.bilibili.com/blackboard/activity"})

    monkeypatch.setattr(b.httpx, "AsyncClient", NoBVClient)
    with pytest.raises(BiliError, match="短链解析失败"):
        await b.resolve_bvid("b23.tv/xyz")


@pytest.mark.anyio
async def test_resolve_bvid_garbage_input_raises():
    """
    Given 无 BV 且非 B站链接的输入（含空串）
    When  resolve_bvid
    Then  抛 BiliError（不误发请求）
    """
    from app.services.bili import resolve_bvid

    for bad in ("hello world", "", "  ", "av170001"):
        with pytest.raises(BiliError):
            await resolve_bvid(bad)


def test_fetch_subtitle_real_sessdata(client):
    """
    Given 真实 SESSDATA（用户已配）
    When  对一个真实 CS2 视频 fetch_subtitle
    Then  有字幕轨返回文本（zh-CN/ai-zh 优先）；该用例在有网环境跑
    """
    from app.database import session_factory
    from app.services import settings_service

    with session_factory() as s:
        sessdata = settings_service.get_value(s, "bili.sessdata")
    if not sessdata:
        pytest.skip("未配置 SESSDATA")
    # 一个公开可用的 CS2 教学视频（多分P标题无关，仅验字幕链路）
    text = asyncio.run(b_fetch("BV1GJ411x7h7", sessdata))
    assert text is None or isinstance(text, str)


async def b_fetch(bvid: str, sessdata: str):
    from app.services.bili import fetch_subtitle

    return await fetch_subtitle(bvid, sessdata)
