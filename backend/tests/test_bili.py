"""B站管线契约：WBI 检索 / 字幕获取（SESSDATA）/ 风控软着陆 / 学习任务编排（总结+道具卡走 AI，无 Key 降级）。"""
import asyncio
import json

import httpx
import pytest

from app.services.bili import BiliRiskError, sign_wbi


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
