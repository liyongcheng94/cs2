"""四维分析 JSON schema（阶段 0 定型）与 AI 复盘输出模型。

基线指标字段全预留、默认 None：解析引擎能算的先算，算不了的留空，后续迭代不改表。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.1"

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
    victim_x: float | None = None  # 死亡位置（游戏坐标，散点图用）
    victim_y: float | None = None
    killer_x: float | None = None  # 击杀者位置
    killer_y: float | None = None


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
    effective_buy_ratio: float | None = None  # 装备价值 / 总资金（无总资金列，留 null）
    first_kill_conversion: float | None = None  # 首杀方赢下该回合的概率
    eco_win_rate: float | None = None  # 1.1：eco/force 回合胜率（经济抗压能力）
    full_buy_lose_rate: float | None = None  # 1.1：full buy 回合败率（资源转化能力）


class ThrowEvent(BaseModel):
    round_no: int | None = None
    grenade_type: str | None = None  # smoke/flash/molotov/he/decoy
    point: str | None = None
    effective: bool | None = None
    blind_seconds: float | None = None


class GrenadeUsage(BaseModel):
    """分道具购买 vs 使用（1.1）：买了没扔 = 经济浪费。"""

    grenade_type: str
    bought: int = 0  # item_events purchase 计数（按类型映射）
    thrown: int = 0  # grenades 实际投掷数（entity_id 去重）
    waste_rate: float | None = None  # bought>0: max(0, bought-thrown)/bought；捡漏（bought=0 且 thrown>0）记 0.0


class UtilityDim(BaseModel):
    throws: list[ThrowEvent] = Field(default_factory=list)
    blind_median_s: float | None = None  # 致盲敌方时长中位数（抗离群值；1.1 口径仅敌方）
    waste_rate: float | None = None  # 闪光浪费率：1 - 有效闪（敌方致盲>0.5s 数）/ 闪光投掷数
    enemy_blind_s: float | None = None  # 1.1：致盲敌方累计秒数（>0.1s 计入，自闪排除）
    team_blind_s: float | None = None  # 1.1：致盲队友累计秒数（>0.1s 计入，自闪排除）
    usage: list[GrenadeUsage] = Field(default_factory=list)  # 1.1：分道具购买 vs 使用


class AnalysisMeta(BaseModel):
    parser: str
    cost_s: float | None = None
    peak_mem_mb: float | None = None


class HighlightMoment(BaseModel):
    """高光时刻（1.1，借鉴 cs2-highlights-maker 评分思路的纯解析版）。"""

    round_no: int | None = None
    start_tick: int | None = None
    end_tick: int | None = None
    kills: int = 0
    headshots: int = 0
    score: float | None = None
    label: str | None = None  # 双杀/3K/4K/ACE
    round_won: bool | None = None
    clutch: bool | None = None  # 时刻起点队内存活 ≤2（残局近似）


class FourDimAnalysis(BaseModel):
    schema_version: str = SCHEMA_VERSION
    match_id: str
    deaths: DeathDim = Field(default_factory=DeathDim)
    economy: EconomyDim = Field(default_factory=EconomyDim)
    utility: UtilityDim = Field(default_factory=UtilityDim)
    duels: DuelDim = Field(default_factory=DuelDim)
    highlights: list[HighlightMoment] = Field(default_factory=list)  # 1.1：TopN 可看性时刻
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
