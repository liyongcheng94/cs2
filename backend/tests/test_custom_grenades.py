"""学道具 v4：自建道具 + 来源/地图/点位筛选。

场景（Given/When/Then）：
  C1 Given 用户提交自建道具（地图/点位/类型/站位/时机/描述/可选贴图）
      When POST /bili/grenades/custom
      Then 新建 GrenadeCard（source_hash="custom:{uuid}"，bvid=None，video_ts=None）
  C2 Given 自建卡 When POST 带 files 贴图 Then 贴图挂到新卡上（与已有上传同路径）
  C3 Given 校验失败（map_name 缺失）When POST Then 422/400 不落库
  F1 Given 库里有视频卡+自建卡 When GET /bili/grenades?source=video Then 只返回视频卡
  F2 When ?source=custom Then 只返回自建卡
  F3 When ?point=A1 Then 点位精确（大小写不敏感）匹配
  F4 列表返回新增 source 字段（"video"/"custom"）
"""
from __future__ import annotations

import pytest
from sqlmodel import select

from app.database import session_factory
from app.models import GrenadeCard


def _seed_video_card(map_name="Mirage", point="A1", bvid="BV1seedAAA1") -> int:
    with session_factory() as s:
        c = GrenadeCard(
            map_name=map_name, point=point, grenade_type="烟雾弹",
            source_hash=f"hash-{bvid}-{point}", bvid=bvid,
            content_md="视频学来的卡",
        )
        s.add(c)
        s.commit()
        s.refresh(c)
        return c.id


class TestCustomGrenade:
    def test_create_custom_card(self, client):
        """C1+C4：自建卡落库，无 bvid、source=custom。"""
        resp = client.post("/api/bili/grenades/custom", json={
            "map_name": "Mirage", "point": "A1", "grenade_type": "烟雾弹",
            "stance": "A1 火点", "timing": "开局", "content_md": "自己研究的点位",
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["source"] == "custom"
        assert body["bvid"] is None
        with session_factory() as s:
            card = s.get(GrenadeCard, body["id"])
            assert card is not None
            assert card.bvid is None
            assert card.source_hash.startswith("custom:")

    def test_custom_card_with_image(self, client, tmp_path):
        """C2：自建 + 同时传贴图。"""
        import io

        png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
        resp = client.post(
            "/api/bili/grenades/custom",
            data={"map_name": "Mirage", "point": "VIP", "grenade_type": "烟雾弹", "content_md": "带图自建"},
            files={"files": ("a.png", io.BytesIO(png), "image/png")},
        )
        assert resp.status_code == 200, resp.text
        card_id = resp.json()["id"]
        imgs = client.get(f"/api/bili/grenades/{card_id}/images").json()
        assert len(imgs) == 1

    def test_custom_requires_map_name(self, client):
        """C3：map_name 缺失 → 400，不落库。"""
        resp = client.post("/api/bili/grenades/custom", json={"content_md": "没地图"})
        assert resp.status_code == 400
        with session_factory() as s:
            assert s.exec(select(GrenadeCard).where(GrenadeCard.source_hash.startswith("custom:"))).first() is None


class TestSourceFilter:
    def test_filter_source_video(self, client):
        """F1：?source=video 只返回视频卡。"""
        vid = _seed_video_card()
        client.post("/api/bili/grenades/custom", json={"map_name": "Mirage", "point": "B", "grenade_type": "闪光弹", "content_md": "自建"})
        rows = client.get("/api/bili/grenades", params={"source": "video"}).json()
        assert all(r["source"] == "video" for r in rows)
        assert any(r["id"] == vid for r in rows)

    def test_filter_source_custom(self, client):
        """F2：?source=custom 只返回自建卡。"""
        _seed_video_card()
        resp = client.post("/api/bili/grenades/custom", json={"map_name": "Mirage", "point": "B", "grenade_type": "闪光弹", "content_md": "自建"})
        cid = resp.json()["id"]
        rows = client.get("/api/bili/grenades", params={"source": "custom"}).json()
        assert [r["id"] for r in rows] == [cid]

    def test_filter_point(self, client):
        """F3：?point=A1 精确匹配（大小写不敏感）。"""
        _seed_video_card(point="A1")
        _seed_video_card(point="palace", bvid="BV1seedAAA2")
        rows = client.get("/api/bili/grenades", params={"point": "a1"}).json()
        assert all((r["point"] or "").lower() == "a1" for r in rows)
        assert len(rows) == 1

    def test_list_returns_source_field(self, client):
        """F4：列表每行带 source 字段。"""
        _seed_video_card()
        rows = client.get("/api/bili/grenades").json()
        assert rows and all("source" in r for r in rows)
        assert rows[0]["source"] == "video"
