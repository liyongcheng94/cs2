"""学道具 v2 Phase 1.2+1.3：zone 列幂等迁移 + 收藏 PATCH。

场景：
Given 旧库 grenadecard 无 zone/favorited 列
When 应用启动跑迁移（重复启动多次）
Then 列存在且再次启动不炸（幂等）

Given 一张道具卡
When PATCH /api/bili/grenades/{id}/favorite {"favorited": true}
Then 该卡 favorited 翻转；GET /api/bili/grenades 返回 favorited 字段
"""
from fastapi.testclient import TestClient


class TestZoneMigration:
    def test_migration_adds_columns_idempotent(self, client: TestClient, tmp_path, monkeypatch):
        """
        Given 新数据目录（首次启动已建表并迁移）
        When 再次 create_db_and_tables（模拟重启）
        Then 不抛异常且 zone/favorited 列可写
        """
        import os

        from app.database import create_db_and_tables

        # client 夹具已跑过一次 lifespan（建表+迁移）；再跑两次验证幂等
        monkeypatch.setenv("CS2HQ_DATA_DIR", str(tmp_path))
        create_db_and_tables()
        create_db_and_tables()  # 第二次：列已存在 → except 分支

        import sqlite3

        conn = sqlite3.connect(str(tmp_path / "cs2hq.db"))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(grenadecard)").fetchall()}
        conn.close()
        assert "zone" in cols, "zone 列未迁移"
        assert "favorited" in cols, "favorited 列未迁移"

    def test_card_persists_zone(self, client: TestClient):
        """
        Given AI 输出带 zone 的道具卡
        When 学习入库
        Then zone 持久化
        """
        # zone 由 handler 落库（c.get("zone")）——在 Phase 1.2 中 handler 写入
        from sqlmodel import select

        from app.database import session_factory
        from app.models import GrenadeCard

        with session_factory() as s:
            s.add(GrenadeCard(
                map_name="Mirage", point="拱门", grenade_type="燃烧弹",
                stance="B小", timing="开局", video_ts="43.2", bvid="BV1zone00001",
                content_md="贴B小丢", source_hash="zone-hash-1", zone="中路",
            ))
            s.commit()
            row = s.exec(select(GrenadeCard).where(GrenadeCard.source_hash == "zone-hash-1")).first()
            assert row is not None and row.zone == "中路"


class TestFavoritePatch:
    def test_patch_favorite_flips(self, client: TestClient):
        """
        Given 一张道具卡
        When PATCH favorite true → 再 PATCH false
        Then favorited 随之翻转，响应体返回最新值
        """
        from sqlmodel import select

        from app.database import session_factory
        from app.models import GrenadeCard

        with session_factory() as s:
            card = GrenadeCard(
                map_name="Mirage", point="VIP", grenade_type="烟雾弹",
                stance="A1", timing="开局", video_ts="", bvid="BV1fav000001",
                content_md="x", source_hash="fav-hash-1",
            )
            s.add(card)
            s.commit()
            card_id = card.id

        r1 = client.patch(f"/api/bili/grenades/{card_id}/favorite", json={"favorited": True})
        assert r1.status_code == 200, r1.text
        assert r1.json()["favorited"] is True

        with session_factory() as s:
            row = s.get(GrenadeCard, card_id)
            assert row.favorited is True

        r2 = client.patch(f"/api/bili/grenades/{card_id}/favorite", json={"favorited": False})
        assert r2.status_code == 200 and r2.json()["favorited"] is False

    def test_patch_404_on_missing(self, client: TestClient):
        """不存在的卡 → 404。"""
        r = client.patch("/api/bili/grenades/99999/favorite", json={"favorited": True})
        assert r.status_code == 404

    def test_grenades_list_has_zone_and_favorited(self, client: TestClient):
        """GET /api/bili/grenades 响应含 zone 与 favorited 字段（前端渲染依赖）。"""
        from sqlmodel import select

        from app.database import session_factory
        from app.models import GrenadeCard

        with session_factory() as s:
            s.add(GrenadeCard(
                map_name="Mirage", point="A1", grenade_type="闪光弹",
                stance="A1", timing="开局", video_ts="", bvid="BV1list00001",
                content_md="x", source_hash="list-hash-1", zone="A区", favorited=True,
            ))
            s.commit()

        body = client.get("/api/bili/grenades").json()
        assert isinstance(body, list) and body, body
        item = body[0]
        assert "zone" in item and "favorited" in item
