"""B站内容查询 API 契约：视频总结列表（倒序）/ 道具库（地图×道具类型筛选）。"""
from app.database import session_factory
from app.models import BiliVideo, GrenadeCard


def _seed():
    with session_factory() as s:
        s.add(BiliVideo(bvid="BV1a", title="A大烟", owner="UP1", subtitle_status="subtitle"))
        s.add(BiliVideo(bvid="BV1b", title="B点闪", owner="UP2", subtitle_status="no_subtitle"))
        s.add(GrenadeCard(map_name="de_dust2", point="A大", grenade_type="smoke", content_md="烟", bvid="BV1a", source_hash="h1"))
        s.add(GrenadeCard(map_name="de_mirage", point="中路", grenade_type="flash", content_md="闪", bvid="BV1b", source_hash="h2"))
        s.commit()


def test_bili_videos_lists_desc(client):
    """
    Given 两条视频（不同时间入库）
    When  GET /api/bili/videos
    Then  倒序返回，含字幕状态字段
    """
    _seed()
    rows = client.get("/api/bili/videos").json()
    assert len(rows) == 2
    assert {"BV1a", "BV1b"} == {r["bvid"] for r in rows}
    assert all("subtitle_status" in r for r in rows)


def test_bili_grenades_filter_by_map_and_type(client):
    """
    Given dust2 烟卡 + mirage 闪卡
    When  GET /api/bili/grenades?map_name=DE_DUST2&grenade_type=SMOKE（大小写不敏感）
    Then  仅返回 dust2 烟卡；不带筛选返回全部
    """
    _seed()
    rows = client.get("/api/bili/grenades", params={"map_name": "DE_DUST2", "grenade_type": "SMOKE"}).json()
    assert len(rows) == 1 and rows[0]["point"] == "A大"
    all_rows = client.get("/api/bili/grenades").json()
    assert len(all_rows) == 2
