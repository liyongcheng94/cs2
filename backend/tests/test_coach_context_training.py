"""教练上下文升级（A）+ 训练处方闭环（B）契约测试。

场景（Given/When/Then）：
A. 上下文升级
  A1 Given 赛季统计快照存在 When chat Then instruction 注入赛季摘要（rating/ADR/爆头率/主图场次）
  A2 Given 道具卡库有卡 When chat Then instruction 注入道具卡索引（地图/点位/类型/时间戳），教练可引用
  A3 Given PlayerProfile 无 hs_rate 而 SeasonStats 有 When chat Then instruction 用赛季真实爆头率（动态覆盖旧截图数）
  A4 Given 无任何数据 When chat Then 不炸（上下文缺块跳过）
B. 训练处方闭环
  B1 Given 教练回复带 ```training JSON 块 When chat Then 解析出 TrainingCard 行（去重）
  B2 Given 教练回复无处方块 When chat Then 不建卡（纯文本对话不受影响）
  B3 Given 处方卡已存在同 content_hash When 相同处方再来 Then 幂等不重复
  B4 Given TrainingCard 行存在 When GET /chat/training-cards Then 返回列表（含任务关联）
  B5 Given 处方卡 When POST /chat/training-cards/{id}/to-task Then 创建任务中心 Task（type=training_practice）
  B6 Given training_practice 任务 When /run Then 直接 success（记录完成，无需外部 handler）
"""
from __future__ import annotations

import json

import httpx
import pytest


@pytest.fixture()
def stub_ai_bridge(client, monkeypatch):
    """AI 桩：可编程回复（默认带处方块）。"""
    import app.services.chat_coach as cc
    from app.services.ai_client import AiClient

    seen = []
    holder = {"reply": "教练回复"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"ok": True}, headers={"set-cookie": "mv_session=t; Path=/"})
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"text": holder["reply"]})

    def fake_build(session):
        return AiClient(provider="mindvault", mv_base_url="http://stub", mv_password="pw",
                        transport=httpx.MockTransport(handler))

    monkeypatch.setattr(cc, "build_ai_client", fake_build)
    seen_holder = {"seen": seen, "reply": holder}
    return seen_holder


def _seed_session(client) -> int:
    return client.post("/api/chat/sessions").json()["id"]


REPLY_WITH_PLAN = """本周重点练爆头线。

```training
{"items": [{"title": "Aim Botz 爆头流", "detail": "只点头，200 个爆头击杀", "duration_min": 30, "check": "爆头击杀 200"}]}
```

练完回来报数。"""


class TestContextUpgrade:
    def test_injects_season_summary(self, client, stub_ai_bridge):
        """A1：赛季统计 → instruction 注入摘要。"""
        from app.database import session_factory
        from app.models import SeasonStats

        with session_factory() as s:
            s.add(SeasonStats(season_id="recent", payload={
                "rating": 0.98, "adr": 73.95, "headShotRatio": 0.35, "kd": 0.98,
                "cnt": 152, "winRate": 0.39, "entryKillRatio": 0.15,
                "hotMaps": [{"map": "de_dust2", "mapName": "炙热沙城Ⅱ", "totalMatch": 106,
                             "winCount": 44, "firstKillNum": 266, "firstDeathNum": 243}],
            }))
            s.commit()

        sid = _seed_session(client)
        client.post("/api/chat", json={"session_id": sid, "content": "我最近水平怎么样"})
        instruction = stub_ai_bridge["seen"][0]["instruction"]
        assert "0.98" in instruction and "73.95" in instruction
        assert "152" in instruction  # 场次
        assert "炙热沙城Ⅱ" in instruction or "dust2" in instruction

    def test_injects_grenade_card_index(self, client, stub_ai_bridge):
        """A2：道具卡索引 → 教练可引用具体卡。"""
        from app.database import session_factory
        from app.models import GrenadeCard

        with session_factory() as s:
            s.add(GrenadeCard(map_name="Mirage", point="VIP", grenade_type="烟雾弹",
                              stance="匪口双架", timing="开局 15s", video_ts="70.32",
                              bvid="BV1U2gf6GEuZ", content_md="封 VIP 视野", source_hash="idx-1",
                              zone="中路"))
            s.commit()

        sid = _seed_session(client)
        client.post("/api/chat", json={"session_id": sid, "content": "Mirage VIP 烟怎么扔"})
        instruction = stub_ai_bridge["seen"][0]["instruction"]
        assert "Mirage" in instruction and "VIP" in instruction
        assert "70.32" in instruction  # 时间戳可引用
        assert "BV1U2gf6GEuZ" in instruction

    def test_profile_hs_rate_dynamic_override(self, client, stub_ai_bridge):
        """A3：画像旧爆头率 0.319 → 赛季真实 0.35 优先展示。"""
        from app.database import session_factory
        from app.models import PlayerProfile, SeasonStats

        with session_factory() as s:
            # baseline 种子由 lifespan 创建（hs_rate=0.319 旧截图值），这里只补赛季快照
            prof = s.get(PlayerProfile, "baseline")
            assert prof is not None and prof.data.get("hs_rate") == 0.319
            s.add(SeasonStats(season_id="recent", payload={"headShotRatio": 0.35, "cnt": 152}))
            s.commit()

        sid = _seed_session(client)
        client.post("/api/chat", json={"session_id": sid, "content": "我的爆头率"})
        instruction = stub_ai_bridge["seen"][0]["instruction"]
        assert "0.35" in instruction  # 赛季真实值
        assert "0.319" not in instruction  # 旧值被覆盖

    def test_empty_context_no_crash(self, client, stub_ai_bridge):
        """A4：无任何数据 → 正常回复（上下文缺块跳过）。"""
        sid = _seed_session(client)
        resp = client.post("/api/chat", json={"session_id": sid, "content": "你好"})
        assert resp.status_code == 200
        assert resp.json()["reply"] == "教练回复"


class TestTrainingCards:
    def test_reply_with_plan_creates_cards(self, client, stub_ai_bridge):
        """B1：回复带 ```training 块 → 解析建卡。"""
        stub_ai_bridge["reply"]["reply"] = REPLY_WITH_PLAN
        sid = _seed_session(client)
        resp = client.post("/api/chat", json={"session_id": sid, "content": "这周练什么"})
        assert resp.status_code == 200

        cards = client.get("/api/chat/training-cards").json()
        assert len(cards) == 1
        c = cards[0]
        assert c["title"] == "Aim Botz 爆头流"
        assert c["detail"] == "只点头，200 个爆头击杀"
        assert c["duration_min"] == 30
        assert c["session_id"] == sid
        assert c["task_id"] is None  # 未入任务中心

    def test_reply_without_plan_no_card(self, client, stub_ai_bridge):
        """B2：纯文本回复 → 不建卡。"""
        stub_ai_bridge["reply"]["reply"] = "今天状态不错，保持。"
        sid = _seed_session(client)
        client.post("/api/chat", json={"session_id": sid, "content": "今天感觉如何"})
        assert client.get("/api/chat/training-cards").json() == []

    def test_duplicate_plan_idempotent(self, client, stub_ai_bridge):
        """B3：同一处方重复出现（重发/多轮）→ 幂等不重复建卡。"""
        stub_ai_bridge["reply"]["reply"] = REPLY_WITH_PLAN
        sid = _seed_session(client)
        client.post("/api/chat", json={"session_id": sid, "content": "这周练什么"})
        sid2 = _seed_session(client)
        client.post("/api/chat", json={"session_id": sid2, "content": "再给一遍计划"})
        cards = client.get("/api/chat/training-cards").json()
        assert len(cards) == 1  # content_hash 去重

    def test_malformed_plan_block_ignored(self, client, stub_ai_bridge):
        """B 边界：处方块 JSON 非法 → 忽略（不炸对话）。"""
        stub_ai_bridge["reply"]["reply"] = "计划如下\n```training\n{not-json}\n```"
        sid = _seed_session(client)
        resp = client.post("/api/chat", json={"session_id": sid, "content": "练什么"})
        assert resp.status_code == 200
        assert client.get("/api/chat/training-cards").json() == []

    def test_card_to_task(self, client, stub_ai_bridge):
        """B5：处方卡 → 一键入任务中心（type=training_practice）。"""
        stub_ai_bridge["reply"]["reply"] = REPLY_WITH_PLAN
        sid = _seed_session(client)
        client.post("/api/chat", json={"session_id": sid, "content": "这周练什么"})
        card = client.get("/api/chat/training-cards").json()[0]

        resp = client.post(f"/api/chat/training-cards/{card['id']}/to-task")
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        # 任务中心可见 + 直接 run 即 success（训练打卡不需要外部 handler）
        task = client.get(f"/api/tasks/{task_id}").json()
        assert task["type"] == "training_practice"
        assert task["payload"]["title"] == "Aim Botz 爆头流"
        run = client.post(f"/api/tasks/{task_id}/run")
        assert run.json()["status"] == "success"

        # 卡片状态联动：task_id 回填
        cards = client.get("/api/chat/training-cards").json()
        assert cards[0]["task_id"] == task_id

    def test_to_task_twice_rejected(self, client, stub_ai_bridge):
        """B6：同一卡重复入任务 → 409（防重复打卡）。"""
        stub_ai_bridge["reply"]["reply"] = REPLY_WITH_PLAN
        sid = _seed_session(client)
        client.post("/api/chat", json={"session_id": sid, "content": "练什么"})
        card = client.get("/api/chat/training-cards").json()[0]
        client.post(f"/api/chat/training-cards/{card['id']}/to-task")
        resp = client.post(f"/api/chat/training-cards/{card['id']}/to-task")
        assert resp.status_code == 409

    def test_stream_also_creates_cards(self, client, stub_ai_bridge):
        """B7：流式对话同样解析处方（主路径是 SSE）。"""
        stub_ai_bridge["reply"]["reply"] = REPLY_WITH_PLAN
        sid = _seed_session(client)
        with client.stream("POST", "/api/chat/stream", json={"session_id": sid, "content": "练什么"}) as r:
            for _ in r.iter_text():
                pass
        assert len(client.get("/api/chat/training-cards").json()) == 1
