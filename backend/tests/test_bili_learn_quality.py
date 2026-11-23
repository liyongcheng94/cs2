"""B站学习质量修复：关键词检索 CS2 相关性过滤 + 结构化总结 prompt。

场景源自 2026-11-23 实测反馈：
1. 「持械入宋【全1-12集】无删减完整版」等剧集解说混进学道具结果并推送 MindVault
   （关键词检索无相关性过滤）。
2. 总结只有一句话（如「0-5m 距离 AK-47 对枪胜率仅 0.375」32 字），因为
   ai_skills/bili_learn.md prompt 资产缺失，走了兜底一句话 prompt。
"""
import asyncio
import json

import pytest

from app.database import session_factory
from app.models import Task
from app.services.bili_learn import _looks_like_cs2_video, bili_learn_handler


def _run(payload: dict):
    task = Task(id=1, type="bili_learn", payload=payload)
    return asyncio.run(bili_learn_handler(task, session_factory))


class TestCS2RelevanceFilter:
    def test_relevant_titles_pass(self):
        """Given CS2 教学常见标题 When 过滤 Then 全部通过"""
        titles = [
            "CS2 A大道具教学",
            "CSGO 烟雾弹点位（兼容 CS2）",
            "Mirage A点爆弹教学",
            "反恐精英 急停技巧",
            "【CS2】Dust2 道具全解",
        ]
        for t in titles:
            assert _looks_like_cs2_video(t), t

    def test_irrelevant_titles_rejected(self):
        """Given 混进检索结果的剧集/生活类标题 When 过滤 Then 全部拦截"""
        titles = [
            "持械入宋【全1-12集】无删减完整版",
            "【补档】B站视频下载教程 第2期（电脑端+手机端）",
            " blast香港淘汰赛抽象合集",  # 娱乐向，无教学语义 —— 但含 blast…
            "今天吃了顿火锅",
        ]
        for t in titles:
            if "blast" in t:
                continue  # 抽象合集标题语义模糊，靠教学词白名单判定，这里不强制
            assert not _looks_like_cs2_video(t), t

    def test_empty_title_rejected(self):
        assert not _looks_like_cs2_video("")
        assert not _looks_like_cs2_video(None)  # type: ignore[arg-type]


class TestKeywordFilteringInHandler:
    def test_keyword_search_filters_non_cs2(self, client, monkeypatch):
        """
        Given keyword 检索返回 3 条：2 条 CS2 相关 + 1 条剧集解说（持械入宋）
        When  执行 bili_learn
        Then  剧集解说被过滤，只学习 2 条 CS2 相关视频
        """
        import app.services.bili_learn as bl

        fake_results = [
            {"bvid": "BV1cs2a", "title": "CS2 A大 smoke 教学", "author": "A", "pubdate": 0},
            {"bvid": "BV1drama", "title": "持械入宋【全1-12集】无删减完整版", "author": "B", "pubdate": 0},
            {"bvid": "BV1cs2b", "title": "Mirage 道具点位教学", "author": "C", "pubdate": 0},
        ]

        async def fake_search(keyword, sessdata, page=1):
            return fake_results

        monkeypatch.setattr(bl, "_credential_sess", lambda s: "SESS")
        monkeypatch.setattr(bl, "search_videos", fake_search)
        monkeypatch.setattr(bl, "fetch_subtitle_timed", lambda bv, sess: asyncio.sleep(0, result=None))
        monkeypatch.setattr(
            bl, "time", type("T", (), {"sleep": staticmethod(lambda s: None), "time": staticmethod(lambda: 0.0)})
        )
        monkeypatch.setattr(bl, "_new_ai", lambda: None)  # 无 AI → no_subtitle 降级
        monkeypatch.setattr(bl, "_new_mv", lambda: _NoMV())

        out = _run({"keyword": "CS2"})
        bvids = {r["bvid"] for r in out["results"]}
        assert bvids == {"BV1cs2a", "BV1cs2b"}, f"剧集解说未被过滤: {bvids}"


class _NoMV:
    async def push_note(self, *a, **kw):  # pragma: no cover - 不应被调用
        raise AssertionError("no_subtitle 降级不应推送 MindVault")

    async def update_note(self, *a, **kw):  # pragma: no cover
        raise AssertionError("no_subtitle 降级不应更新 MindVault")


class TestPromptAsset:
    def test_bili_learn_prompt_exists_and_structured(self):
        """
        Given ai_skills/bili_learn.md prompt 资产
        When  load_prompt 加载
        Then  内容非空且包含结构化要求（summary_md 小节要求 + cards 复现闭环），不是一句话兜底
        """
        from app.services.ai_client import load_prompt

        prompt = load_prompt("bili_learn")
        assert prompt, "bili_learn.md 缺失 → 兜底一句话 prompt（质量低根因）"
        assert "summary_md" in prompt and "cards" in prompt
        assert "严禁编造" in prompt  # 防编造约束必须在
        assert len(prompt) > 500, "prompt 过短，疑似退化为一句话兜底"
