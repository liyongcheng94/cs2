"""完美风格完整对局分析 schema（对齐 PWA 客户端 7 个分析维度，ALL/T/CT 切换）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PerfectSummary(BaseModel):
    rounds: int = 0
    round_wins: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    hs_kills: int = 0
    adr: float = 0.0
    opening_kills: int = 0
    opening_deaths: int = 0


class AimDim(BaseModel):
    shots: int = 0
    hits: int = 0
    hit_rate: float = 0.0
    avg_kill_distance: float = 0.0


class EntryDim(BaseModel):
    entry_kills: int = 0
    entry_deaths: int = 0


class TradeDim(BaseModel):
    trade_kills: int = 0
    trade_opportunities: int = 0
    created_opportunities: int = 0


class UtilityDim(BaseModel):
    flash_enemies: int = 0
    flash_teammates: int = 0
    flash_assists: int = 0
    util_damage: float = 0.0


class ClutchAttempt(BaseModel):
    round_no: int
    vs_count: int
    outcome: str  # win / loss / saved
    kills_in_clutch: int = 0


class ClutchDim(BaseModel):
    attempts: list[ClutchAttempt] = Field(default_factory=list)


class MatchupRow(BaseModel):
    opponent_id: str
    opponent_name: str = ""
    my_kills: int = 0
    my_deaths: int = 0
    my_damage: float = 0.0
    their_damage: float = 0.0


class MatchupDim(BaseModel):
    rows: list[MatchupRow] = Field(default_factory=list)


class PerfectAnalysis(BaseModel):
    schema_version: str = "1"
    side: str = "ALL"
    summary: PerfectSummary = Field(default_factory=PerfectSummary)
    aim: AimDim = Field(default_factory=AimDim)
    entry: EntryDim = Field(default_factory=EntryDim)
    trade: TradeDim = Field(default_factory=TradeDim)
    utility: UtilityDim = Field(default_factory=UtilityDim)
    clutch: ClutchDim = Field(default_factory=ClutchDim)
    matchup: MatchupDim = Field(default_factory=MatchupDim)
