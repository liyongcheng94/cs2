"""AI 复盘管线契约：ai_client（OpenAI 兼容）+ ReviewOutput 护栏 + Rule-based 唯一重点 + 幂等推送。"""
import json

import httpx
import pytest

from app.schemas.analysis import FourDimAnalysis
from app.services.report import (
    PromptVersion,
    build_report,
    compute_source_hash,
    rule_based_focus,
    render_markdown,
)


def _analysis(**kw) -> FourDimAnalysis:
    from app.schemas.analysis import (
        AnalysisMeta, DeathDim, DuelBucket, DuelDim, EconomyDim, UtilityDim,
    )
    base = dict(
        match_id="PVP@T1",
        deaths=DeathDim(disadvantaged_rate=0.35),
        duels=DuelDim(
            by_weapon_distance=[DuelBucket(distance="0-5m", weapon="AK-47", kills=3, deaths=5, win_rate=0.375)],
            first_strike_win_rate=0.55,
        ),
        economy=EconomyDim(effective_buy_ratio=0.72, first_kill_conversion=0.61),
        utility=UtilityDim(blind_median_s=2.1, waste_rate=0.18),
        meta=AnalysisMeta(parser="spike", cost_s=3.2, peak_mem_mb=800),
    )
    base.update(kw)
    return FourDimAnalysis(**base)


def test_source_hash_depends_on_match_and_prompt_version():
    """
    Given 同一 matchId 不同 prompt_version
    When  compute_source_hash
    Then  hash 不同（提示词迭代生成 v2 新笔记，旧笔记保留）
    """
    h1 = compute_source_hash("PVP@T1", "v1")
    h2 = compute_source_hash("PVP@T1", "v2")
    assert h1 != h2
    assert h1 == compute_source_hash("PVP@T1", "v1")


def test_rule_based_focus_hard_redline_first():
    """
    Given 对枪矩阵 0-5m 胜率 0.22（< 30% 硬红线）
    When  rule_based_focus
    Then  今日唯一重点 = 近战急停（Rule-based 优先，AI 不自由发挥）
    """
    focus = rule_based_focus(
        _analysis(duels={"by_weapon_distance": [{"distance": "0-5m", "weapon": "AK-47", "kills": 2, "deaths": 9, "win_rate": 0.22}]})
    )
    assert focus is not None and "近战" in focus and "急停" in focus


def test_rule_based_focus_utility_redline():
    """
    Given 道具浪费率 > 0.35（硬红线）
    When  rule_based_focus
    Then  今日唯一重点 = 道具专项
    """
    a = _analysis(utility={"blind_median_s": 2.1, "waste_rate": 0.42})
    assert "道具" in rule_based_focus(a)


def test_rule_based_focus_falls_back_to_ai_zone():
    """
    Given 无任何硬红线触发
    When  rule_based_focus
    Then  返回 None（由 AI 在证据链内自由选择唯一重点）
    """
    a = _analysis(
        duels={"by_weapon_distance": [{"distance": "5-15m", "weapon": "AK-47", "win_rate": 0.55}], "first_strike_win_rate": 0.6},
        deaths={"disadvantaged_rate": 0.12},
        economy={"effective_buy_ratio": 0.85, "first_kill_conversion": 0.7},
        utility={"blind_median_s": 3.0, "waste_rate": 0.2},
    )
    assert rule_based_focus(a) is None


def test_render_markdown_contains_sections():
    """
    Given ReviewOutput + 四维分析
    When  render_markdown
    Then  Markdown 含失误/高光/今日唯一重点/明日清单四节
    """
    from app.schemas.analysis import ReviewOutput, ReviewPoint

    review = ReviewOutput(
        match_id="PVP@T1",
        mistakes=[ReviewPoint(title="近战白给", evidence="duels.by_weapon_distance[0].win_rate=0.375", severity="high")],
        highlights=["首杀转化率 0.61"],
        today_focus="近战急停",
        tomorrow=["aim_botz 10 分钟"],
    )
    md = render_markdown(review, _analysis())
    assert "## 失误 Top3" in md and "## 高光" in md
    assert "## 今日唯一重点" in md and "## 明日练什么" in md
    assert "duels.by_weapon_distance[0].win_rate" in md


@pytest.mark.anyio
async def test_build_report_valid_json_path():
    """
    Given AI 桩返回合法 ReviewOutput JSON
    When  build_report
    Then  产出 ReviewOutput + markdown，无降级标记
    """
    from app.services.ai_client import AiClient

    good = {
        "match_id": "PVP@T1",
        "mistakes": [{"title": "m", "evidence": "e", "severity": "high"}],
        "highlights": ["h"],
        "today_focus": "f",
        "tomorrow": ["t1"],
    }

    class StubAi(AiClient):
        def __init__(self):
            super().__init__(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 0})))

        async def chat(self, system, user):
            return json.dumps(good, ensure_ascii=False)

    review, md, degraded = await build_report(_analysis(), ai=StubAi(), focus=None)
    assert degraded is False
    assert review.today_focus == "f"
    assert "## 今日唯一重点" in md


@pytest.mark.anyio
async def test_build_report_invalid_json_degrades():
    """
    Given AI 桩返回非法 JSON（且重试后仍非法）
    When  build_report
    Then  degraded=True（纯文本降级，不阻塞推送）
    """
    from app.services.ai_client import AiClient

    class BadAi(AiClient):
        def __init__(self):
            super().__init__(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 0})))

        async def chat(self, system, user):
            return "这不是JSON{{"

    review, md, degraded = await build_report(_analysis(), ai=BadAi(), focus=None)
    assert degraded is True
    assert review is None
    assert md  # 降级纯文本复盘仍产出 markdown


def test_rule_based_focus_economic_redline():
    """
    Given 满编局败率 60%（资源转化差）且无其他红线
    When  rule_based_focus
    Then  返回资源转化指令（经济硬红线）
    """
    from app.schemas.analysis import EconomyDim, FourDimAnalysis

    a = FourDimAnalysis(match_id="PVP@E", economy=EconomyDim(full_buy_lose_rate=0.6))
    focus = rule_based_focus(a)
    assert focus is not None and "满编" in focus


def test_ai_review_prompt_carries_waste_rate_glossary():
    """
    Given 数据审计（2026-11-26）确认两处 waste_rate 口径易混
    When  _ai_review 组装 system prompt（无外部 prompt 文件，走 fallback）
    Then  prompt 必须同时说明「闪光效率浪费」与「道具买而不扔」两个口径，防止 AI 混用
    """
    import inspect

    from app.services import report as rp

    src = inspect.getsource(rp._ai_review)
    assert "闪光效率浪费" in src
    assert "买而不扔" in src
    assert "usage[].waste_rate" in src


def test_near_range_redline_ignores_low_sample_cells():
    """
    Given 数据审计（2026-11-26）确认单场矩阵格子样本常为 1（0/1→0% 属统计噪音）
    When rule_based_focus 检查 0-5m 对枪红线
    Then 样本 <3 的格子不触发硬红线；样本 ≥3 且 <30% 才触发
    """
    from app.schemas.analysis import DuelBucket, DuelDim, FourDimAnalysis
    from app.services import report as rp

    def _analysis(buckets):
        a = FourDimAnalysis(match_id="M")
        a.duels = DuelDim(by_weapon_distance=buckets)
        return a

    low = DuelBucket(distance="0-5m", weapon="smg", kills=0, deaths=1, win_rate=0.0)
    assert rp.rule_based_focus(_analysis([low])) is None  # 0/1 不触发

    solid = DuelBucket(distance="0-5m", weapon="smg", kills=1, deaths=9, win_rate=0.1)
    assert rp.rule_based_focus(_analysis([solid])) is not None  # 1/10 触发


def test_ai_review_prompt_carries_low_sample_guard():
    """
    Given AI 曾把 0/1 的 0% 列为 high 级失误（统计噪音误读）
    When _ai_review 组装 prompt
    Then prompt 必须声明样本 <3 的矩阵格子不作证据
    """
    import inspect

    from app.services import report as rp

    src = inspect.getsource(rp._ai_review)
    assert "样本" in src and "不足以下结论" in src
