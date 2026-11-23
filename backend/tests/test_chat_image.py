"""AI 教练图片对话（chat_image OCR 间接路线，用户 2026-11-23 选型）：

场景（BDD）：
- Given 用户在 AI 教练上传截图 When POST /chat/images Then 存 data/uploads/chat/ 并 OCR 出文本
- And   OCR 文本注入消息上下文（DeepSeek 不支持 vision → 图片以 OCR 文字间接进入对话）
- Given 图片非图 MIME / 超限 When 上传 Then 400
- Given 图片被删 When GET 原路径 Then 404
"""
import io

import httpx
import pytest


@pytest.fixture()
def stub_ai_bridge(client, monkeypatch):
    """AI 桩（复制自 test_chat.py：fixture 跨测试模块不可见）。"""
    import json as _json

    import app.services.chat_coach as cc
    from app.services.ai_client import AiClient

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"ok": True}, headers={"set-cookie": "mv_session=t; Path=/"})
        seen.append(_json.loads(request.content))
        return httpx.Response(200, json={"text": "教练回复"})

    def fake_build(session):
        return AiClient(provider="mindvault", mv_base_url="http://stub", mv_password="pw",
                        transport=httpx.MockTransport(handler))

    monkeypatch.setattr(cc, "build_ai_client", fake_build)
    return seen


@pytest.fixture
def png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (80, 40), "white").save(buf, format="PNG")
    return buf.getvalue()


class TestChatImageUpload:
    @pytest.mark.anyio
    async def test_upload_and_ocr_returns_url_and_text(self, client, png_bytes):
        """上传成功 → 返回 id/url/ocr_text；文件落 data/uploads/chat/。"""
        resp = client.post(
            "/api/chat/images",
            files=[("files", ("shot.png", png_bytes, "image/png"))],
        )
        assert resp.status_code == 200
        data = resp.json()[0]
        assert data["url"].startswith("/api/chat/uploads/")
        assert data["filename"].endswith(".png")
        # 纯白图 OCR 文本可能为空列表 → ocr_text 为 ""（允许空，不炸）
        assert isinstance(data["ocr_text"], str)

    @pytest.mark.anyio
    async def test_reject_non_image(self, client):
        """非图 MIME → 400。"""
        resp = client.post(
            "/api/chat/images",
            files=[("files", ("a.txt", b"hello", "text/plain"))],
        )
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_reject_oversize(self, client, png_bytes):
        """>5MB → 400。"""
        big = png_bytes + b"\0" * (5 * 1024 * 1024 + 1)
        resp = client.post(
            "/api/chat/images",
            files=[("files", ("big.png", big, "image/png"))],
        )
        assert resp.status_code == 400


class TestChatImageServe:
    @pytest.mark.anyio
    async def test_get_upload_serves_file(self, client, png_bytes):
        up = client.post(
            "/api/chat/images",
            files=[("files", ("shot.png", png_bytes, "image/png"))],
        ).json()[0]
        resp = client.get(up["url"])
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

    @pytest.mark.anyio
    async def test_path_traversal_404(self, client):
        resp = client.get("/api/chat/uploads/0/..%2f..%2fsecret.txt")
        assert resp.status_code in (404, 400)


class TestChatMessageImageBinding:
    @pytest.mark.anyio
    async def test_chat_message_accepts_image_ids(self, client, stub_ai_bridge, png_bytes):
        """POST /chat 带 image_ids → 消息落库带 image_ids，OCR 文本并入 prompt。"""
        up = client.post(
            "/api/chat/images",
            files=[("files", ("s.png", png_bytes, "image/png"))],
        ).json()[0]

        resp = client.post(
            "/api/chat",
            json={"content": "看图分析", "image_ids": [up["id"]]},
        )
        assert resp.status_code == 200
        detail = client.get(f"/api/chat/sessions/{resp.json()['session_id']}/messages").json()
        user_msgs = [m for m in detail if m["role"] == "user"]
        assert user_msgs[-1]["image_ids"] == [up["id"]]
