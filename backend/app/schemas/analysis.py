"""四维分析 JSON schema（阶段 0 定型）与 AI 复盘输出模型。

基线指标字段全预留、默认 None：解析引擎能算的先算，算不了的留空，后续迭代不改表。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"

DistanceBucket = Literal["0-5m", "5-15m", "15m+"]


class DuelBucket(BaseModel):
    distance: DistanceBucket
    weapon: str
    kills: int | None = None
    deaths: int | None = None
    win_rate: float | None = None


class DuelDim(BaseModel):
    by_weapon_distance: list[DuelBucket] = Field(default_factory=list)
    first_strike_win_rate: float | None = None  # 先手开枪胜率
    mirror_win_rate: float | None = None  # 同武器镜像对枪胜率


class DeathEvent(BaseModel):
    round_no: int | None = None
    tick: int | None = None
    killer_weapon: str | None = None
    distance_m: float | None = None
    first_duel: bool | None = None  # 是否首杀/首死
    teammate_support: bool | None = None  # 死亡时附近有无队友
    disadvantaged_position: bool | None = None  # 是否劣势枪位（无掩体/被交叉火力覆盖）


class DeathDim(BaseModel):
    events: list[DeathEvent] = Field(default_factory=list)
    buckets: list[DuelBucket] = Field(default_factory=list)  # 死亡距离分桶
    disadvantaged_rate: float | None = None


class BuyDecision(BaseModel):
    round_no: int | None = None
    buy: str | None = None  # full/force/eco
    equip_value: int | None = None
    effective: bool | None = None  # 是否有效购买


class EconomyDim(BaseModel):
    buy_decisions: list[BuyDecision] = Field(default_factory=list)
    effective_buy_ratio: float | None = None  # 装备价值 / 总资金
    first_kill_conversion: float | None = None  # 首杀方赢下该回合的概率


class ThrowEvent(BaseModel):
    round_no: int | None = None
    grenade_type: str | None = None  # smoke/flash/molotov/he/decoy
    point: str | None = None
    effective: bool | None = None
    blind_seconds: float | None = None


class UtilityDim(BaseModel):
    throws: list[ThrowEvent] = Field(default_factory=list)
    blind_median_s: float | None = None  # 致盲时长中位数（抗离群值）
    waste_rate: float | None = None  # 未致盲/未造成伤害的投掷物占比


class AnalysisMeta(BaseModel):
    parser: str
    cost_s: float | None = None
    peak_mem_mb: float | None = None


class FourDimAnalysis(BaseModel):
    schema_version: str = SCHEMA_VERSION
    match_id: str
    deaths: DeathDim = Field(default_factory=DeathDim)
    economy: EconomyDim = Field(default_factory=EconomyDim)
    utility: UtilityDim = Field(default_factory=UtilityDim)
    duels: DuelDim = Field(default_factory=DuelDim)
    meta: AnalysisMeta = Field(
        default_factory=lambda: AnalysisMeta(parser="unknown")
    )


class ReviewPoint(BaseModel):
    """防幻觉证据链：每个失误必须引用分析 JSON 的具体字段/取值。"""

    title: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    severity: Literal["high", "mid", "low"] | None = None


class ReviewOutput(BaseModel):
    schema_version: str = SCHEMA_VERSION
    match_id: str
    mistakes: list[ReviewPoint] = Field(default_factory=list)  # 失误 top3
    highlights: list[str] = Field(default_factory=list)
    today_focus: str = ""  # 今日唯一重点（Rule-based 硬红线优先）
    tomorrow: list[str] = Field(default_factory=list)  # 明日练什么
