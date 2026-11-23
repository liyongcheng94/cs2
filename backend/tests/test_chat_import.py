"""DeepSeek 分享对话导入场景（用户 2026-11-23 需求：把 chat.deepseek.com 分享对话存进 AI 教练）：

- Given 分享对话 JSON（title + messages[{role, content, images:[url]}]）When POST /chat/import
  Then 新建会话 + 逐条落 ChatMessage；图片 url 下载到本地 ChatImage 并绑定 image_ids
- Given 图片下载失败 When 导入 Then 该图跳过（消息文本照常导入），导入不整体失败
- Given 同一分享重复导入 When 再 POST（带 same share_key）Then 返回既有会话 id，不重复落库
- Given 消息无图片 When 导入 Then image_ids 为空
"""
import io

import httpx
import pytest
from PIL import Image


def _png_bytes() -> bytes:
    img = Image.new("RGB", (24, 24), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def stub_ai_bridge(client, monkeypatch):
    """AI 桩（复制自 test_chat.py：fixture 跨测试模块不可见）。导入流程不调 AI，仅为 client 依赖。"""
    import json as _json

    import app.services.chat_coach as cc
    from app.services.ai_client import AiClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"ok": True}, headers={"set-cookie": "mv_session=t; Path=/"})
        return httpx.Response(200, json={"text": "教练回复"})

    def fake_build(session):
        return AiClient(provider="mindvault", mv_base_url="http://stub", mv_password="pw",
                        transport=httpx.MockTransport(handler))

    monkeypatch.setattr(cc, "build_ai_client", fake_build)
    return []


@pytest.fixture
def png_bytes() -> bytes:
    return _png_bytes()


class TestChatImport:
    @pytest.mark.anyio
    async def test_import_creates_session_and_messages(self, client, stub_ai_bridge, monkeypatch):
        """文本消息导入 → 新会话 + 消息按序落库，返回 session_id + imported 数。"""
        resp = client.post("/api/chat/import", json={
            "title": "OMR248 灵敏度分析",
            "share_key": "ljtz9r7v3drkl110fe",
            "messages": [
                {"role": "user", "content": "OMR248 DPI 5001-10000 怎么调 CS2 灵敏度"},
                {"role": "assistant", "content": "eDPI 推荐 800-1000"},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] > 0
        assert data["imported"] == 2
        msgs = client.get(f"/api/chat/sessions/{data['session_id']}/messages").json()
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert "OMR248" in msgs[0]["content"]

    @pytest.mark.anyio
    async def test_import_downloads_images_and_binds(self, client, png_bytes, monkeypatch):
        """带 images 的消息 → 下载存 ChatImage + 绑 image_ids；下载失败跳过不阻断。"""
        calls = {"n": 0}

        def fake_get(url: str, timeout: float = 30.0, headers: dict | None = None):
            calls["n"] += 1
            if "fail.example" in url:
                return None  # 模拟下载失败
            img = Image.new("RGB", (24, 24), "white")
            import io as _io
            buf = _io.BytesIO()
            img.save(buf, format="WEBP")
            return buf.getvalue()

        monkeypatch.setattr("app.api.chat_api._download_image", fake_get)
        resp = client.post("/api/chat/import", json={
            "title": "图分析",
            "share_key": "k2",
            "messages": [
                {"role": "user", "content": "看这张完美平台数据",
                 "images": ["https://ok.example/a.webp", "https://fail.example/b.webp"]},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 1
        assert data["images_downloaded"] == 1  # 失败那张跳过
        msgs = client.get(f"/api/chat/sessions/{data['session_id']}/messages").json()
        assert len(msgs[0]["image_ids"]) == 1

    @pytest.mark.anyio
    async def test_import_idempotent_by_share_key(self, client, stub_ai_bridge):
        """同 share_key 重复导入 → 返回既有会话，不重复落消息。"""
        body = {
            "title": "OMR248",
            "share_key": "same-key",
            "messages": [{"role": "user", "content": "hello"}],
        }
        first = client.post("/api/chat/import", json=body).json()
        second = client.post("/api/chat/import", json=body).json()
        assert second["session_id"] == first["session_id"]
        assert second["imported"] == 0  # 幂等：不再落库
        msgs = client.get(f"/api/chat/sessions/{first['session_id']}/messages").json()
        assert len(msgs) == 1


class TestBindImages:
    @pytest.mark.anyio
    async def test_bind_images_and_boundaries(self, client, png_bytes):
        """补绑图片 → image_ids 写入；越界 400 / 图不存在 404 / 重复绑幂等。"""
        up = client.post(
            "/api/chat/images",
            files=[("files", ("s.png", png_bytes, "image/png"))],
        ).json()[0]
        sid = client.post("/api/chat/import", json={
            "title": "t", "share_key": "bind-k",
            "messages": [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
        }).json()["session_id"]

        ok = client.post("/api/chat/import/bind-images", json={
            "session_id": sid, "bindings": [{"image_id": up["id"], "message_index": 1}]})
        assert ok.status_code == 200 and ok.json()["bound"] == 1
        msgs = client.get(f"/api/chat/sessions/{sid}/messages").json()
        assert msgs[1]["image_ids"] == [up["id"]]

        # 重复绑 → 幂等（不重复追加）
        dup = client.post("/api/chat/import/bind-images", json={
            "session_id": sid, "bindings": [{"image_id": up["id"], "message_index": 1}]})
        assert dup.status_code == 200
        msgs = client.get(f"/api/chat/sessions/{sid}/messages").json()
        assert msgs[1]["image_ids"] == [up["id"]]

        # 越界 → 400
        oob = client.post("/api/chat/import/bind-images", json={
            "session_id": sid, "bindings": [{"image_id": up["id"], "message_index": 9}]})
        assert oob.status_code == 400

        # 图不存在 → 404
        missing = client.post("/api/chat/import/bind-images", json={
            "session_id": sid, "bindings": [{"image_id": 99999, "message_index": 0}]})
        assert missing.status_code == 404


class TestDownloadImage:
    @pytest.mark.anyio
    async def test_download_failure_returns_none(self, client, monkeypatch):
        """_download_image 非 200 / 异常 → None（导入不阻断）。"""
        from app.api.chat_api import _download_image

        class FakeResp:
            status_code = 503
            content = b""

        monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResp())
        assert _download_image("http://x/y.png") is None

        def boom(*a, **k):
            raise OSError("net down")

        monkeypatch.setattr(httpx, "get", boom)
        assert _download_image("http://x/y.png") is None


class TestOcr:
    @pytest.mark.anyio
    async def test_ocr_missing_file_returns_empty(self, monkeypatch, tmp_path):
        """OCR 输入文件不存在 → 空串（不炸）。"""
        from app.services.ocr import ocr_image

        assert ocr_image(tmp_path / "nope.png") == ""
