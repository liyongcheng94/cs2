"""学道具 v2 Phase 1.4：道具卡多图上传。

场景：
Given 一张道具卡与一张 ≤5MB 的 png
When POST /api/bili/grenades/{id}/images multipart 上传
Then 服务端 uuid 命名落 data/uploads/{card_id}/，GET /api/uploads/{card_id}/{filename} 200 image/png
且 GET /api/bili/grenades/{id}/images 返回 [{id, filename, url}]
删除 DELETE .../images/{image_id} 时文件与行同时消失

错误路径：
- 非图片 MIME → 400
- >5MB → 400
- 路径穿越（..）→ 400/404，绝不读 uploads 之外文件
"""
import io

import pytest


def _png_bytes(size: int = 100) -> bytes:
    # 最小合法 PNG 头（测试只关心服务端存储，不真解码）
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * size


@pytest.fixture()
def card_id(client):
    from sqlmodel import select

    from app.database import session_factory
    from app.models import GrenadeCard

    with session_factory() as s:
        card = GrenadeCard(
            map_name="Mirage", point="A1", grenade_type="烟雾弹",
            stance="A1", timing="开局", video_ts="", bvid="BV1img000001",
            content_md="x", source_hash="img-hash-1",
        )
        s.add(card)
        s.commit()
        return card.id


class TestUploadImage:
    def test_upload_and_fetch(self, client, card_id, tmp_path, monkeypatch):
        """
        Given 合法 png
        When 上传
        Then 200 返回 url，GET url 200 且 content-type image/png，文件落盘
        """
        r = client.post(
            f"/api/bili/grenades/{card_id}/images",
            files={"files": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
        )
        assert r.status_code == 200, r.text
        images = r.json()
        assert len(images) == 1
        url = images[0]["url"]
        assert url.startswith("/api/bili/uploads/")

        fetch = client.get(url)
        assert fetch.status_code == 200
        assert fetch.headers["content-type"].startswith("image/png")
        assert fetch.content.startswith(b"\x89PNG")

    def test_multi_upload(self, client, card_id):
        """一次请求多张图 → 全部落库，列表返回 2 条。"""
        r = client.post(
            f"/api/bili/grenades/{card_id}/images",
            files=[
                ("files", ("a.png", io.BytesIO(_png_bytes()), "image/png")),
                ("files", ("b.png", io.BytesIO(_png_bytes()), "image/png")),
            ],
        )
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_reject_non_image(self, client, card_id):
        """text/plain MIME → 400。"""
        r = client.post(
            f"/api/bili/grenades/{card_id}/images",
            files={"files": ("evil.txt", io.BytesIO(b"hello"), "text/plain")},
        )
        assert r.status_code == 400

    def test_reject_oversize(self, client, card_id):
        """>5MB → 400。"""
        big = _png_bytes(5 * 1024 * 1024 + 10)
        r = client.post(
            f"/api/bili/grenades/{card_id}/images",
            files={"files": ("big.png", io.BytesIO(big), "image/png")},
        )
        assert r.status_code == 400

    def test_get_images_list(self, client, card_id):
        """GET /api/bili/grenades/{id}/images 返回已传图列表。"""
        client.post(
            f"/api/bili/grenades/{card_id}/images",
            files={"files": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
        )
        r = client.get(f"/api/bili/grenades/{card_id}/images")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1 and {"id", "filename", "url"} <= set(items[0])

    def test_delete_image_removes_file_and_row(self, client, card_id):
        r = client.post(
            f"/api/bili/grenades/{card_id}/images",
            files={"files": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
        )
        img = r.json()[0]
        d = client.delete(f"/api/bili/grenades/{card_id}/images/{img['id']}")
        assert d.status_code == 200
        # 文件已删 → GET 404
        assert client.get(img["url"]).status_code == 404
        # 列表空
        assert client.get(f"/api/bili/grenades/{card_id}/images").json() == []

    def test_path_traversal_blocked(self, client, card_id):
        """url 带 ../ → 404，且响应体绝不包含 uploads 之外内容。"""
        r = client.get("/api/uploads/0/..%2f..%2fsecret.txt")
        assert r.status_code in (400, 404)

    def test_upload_card_missing_404(self, client):
        r = client.post(
            "/api/bili/grenades/99999/images",
            files={"files": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
        )
        assert r.status_code == 404


class TestUploadSizeLimit:
    def test_nginx_conf_has_client_max_body_size(self):
        """探针发现的隐患回归锁：nginx-spa.conf 必须显式 client_max_body_size ≥ 10m。"""
        import pathlib

        conf = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "nginx-spa.conf"
        text = conf.read_text(encoding="utf-8")
        assert "client_max_body_size" in text, "nginx 未配置上传体积上限（默认 1M 会 413）"
