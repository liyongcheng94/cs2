import pytest
from pydantic import ValidationError

from app.schemas.analysis import (
    DeathDim,
    DuelBucket,
    FourDimAnalysis,
    ReviewOutput,
    ReviewPoint,
)


def test_four_dim_all_fields_optional_default_none():
    """
    Given 四维 schema（阶段 0 定型，基线指标字段预留）
    When  用最小数据构造
    Then  未采集的基线指标默认 None，序列化保留字段名（后续迭代不改表）
    """
    a = FourDimAnalysis(
        match_id="PVP@X",
        deaths=DeathDim(),
        duels={"by_weapon_distance": [{"distance": "0-5m", "weapon": "AK-47"}]},
    )
    dump = a.model_dump()
    assert dump["deaths"]["disadvantaged_rate"] is None
    assert dump["economy"]["effective_buy_ratio"] is None
    assert dump["economy"]["first_kill_conversion"] is None
    assert dump["utility"]["blind_median_s"] is None
    assert dump["utility"]["waste_rate"] is None
    assert dump["duels"]["by_weapon_distance"][0]["win_rate"] is None
    assert dump["duels"]["first_strike_win_rate"] is None
    assert dump["duels"]["mirror_win_rate"] is None


def test_duel_bucket_distance_enums():
    """
    Given 对枪距离分桶只允许 0-5m / 5-15m / 15m+
    When  传入非法桶名
    Then  校验失败
    """
    with pytest.raises(ValidationError):
        DuelBucket(distance="0-10m", weapon="AK-47")


def test_review_point_requires_evidence():
    """
    Given 防幻觉证据链约束：每个失误必须带证据（引用 JSON 字段）
    When  构造没有 evidence 的 ReviewPoint
    Then  校验失败
    """
    with pytest.raises(ValidationError):
        ReviewPoint(title="近战急停不足")
    ReviewPoint(title="近战急停不足", evidence="duels.by_weapon_distance[0].win_rate=0.22")


def test_review_output_full_shape():
    """
    Given 一次合格复盘输出
    When  序列化
    Then  含 top3 失误、高光、今日唯一重点、明日清单
    """
    r = ReviewOutput(
        match_id="PVP@X",
        mistakes=[ReviewPoint(title="m", evidence="e")],
        highlights=["1v3 残局"],
        today_focus="近战急停",
        tomorrow=["aim_botz 10 分钟"],
    )
    assert r.today_focus == "近战急停"
    assert len(r.mistakes) == 1
