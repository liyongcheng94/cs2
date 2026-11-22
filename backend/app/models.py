"""全部表模型（阶段 0 schema 定型；JSON 字段预留四维基线指标，null 允许）。

时间统一 naive UTC（sa_type=NAIVE_DT，与 MindVault 同约定）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, JSON
from sqlmodel import Field, SQLModel

NAIVE_DT = DateTime(timezone=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value_enc: str = ""  # secret 键存 Fernet 密文；普通键存原文
    is_secret: bool = False
    updated_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)


class Task(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    type: str = Field(index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="pending", index=True)  # pending/running/success/failed/NEED_AUTH
    priority: int = Field(default=5)  # 数字越小越先执行；解析类 < 视频总结类
    progress: float = Field(default=0.0)
    result: dict | None = Field(default=None, sa_column=Column(JSON))
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)


class PlayerProfile(SQLModel, table=True):
    key: str = Field(primary_key=True)  # 目前只有 baseline
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)


class Match(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    match_id: str = Field(unique=True, index=True)  # 完美平台 PVP@...
    map_name: str
    score1: int = 0
    score2: int = 0
    win: bool = False
    mode: str = ""
    played_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)
    demo_status: str = Field(
        default="none", index=True
    )  # none/pending_demo/downloaded/analyzed/failed
    raw: dict = Field(default_factory=dict, sa_column=Column(JSON))


class MatchStat(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    match_id: str = Field(unique=True, index=True)
    rating: float | None = None
    pw_rating: float | None = None
    adr: float | None = None
    rws: float | None = None
    hs_rate: float | None = None
    we: float | None = None  # WE 评分（完美平台口径）
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    mvp: int | None = None
    k2: int | None = None
    k3: int | None = None
    k4: int | None = None
    k5: int | None = None
    vs1: int | None = None
    vs2: int | None = None
    vs3: int | None = None
    vs4: int | None = None
    vs5: int | None = None
    raw: dict = Field(default_factory=dict, sa_column=Column(JSON))


class DemoAnalysis(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    match_id: str = Field(unique=True, index=True)
    schema_version: str = "1.0"
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))  # FourDimAnalysis
    parser: str = ""  # demoparser2 / awpy / mock
    cost_s: float | None = None
    peak_mem_mb: float | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)


class Report(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    match_id: str = Field(index=True)
    prompt_version: str = "v1"
    source_hash: str = Field(unique=True, index=True)  # sha256(match_id + prompt_version)
    title: str
    content_md: str = ""
    review_json: dict | None = Field(default=None, sa_column=Column(JSON))  # ReviewOutput
    degraded: bool = False  # 模型输出未过校验降级为纯文本
    pushed: bool = False
    mv_uuid: str | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)


class BiliVideo(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    bvid: str = Field(unique=True, index=True)
    title: str = ""
    owner: str | None = None
    origin: str = "manual"  # manual/search/following
    subtitle_status: str = "none"  # none/subtitle/no_subtitle/failed
    raw: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)


class GrenadeCard(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    map_name: str = Field(index=True)
    point: str | None = None
    grenade_type: str | None = Field(default=None, index=True)  # smoke/flash/molotov/he
    stance: str | None = None
    timing: str | None = None
    video_ts: str | None = None
    bvid: str | None = Field(default=None, index=True)
    content_md: str = ""
    source_hash: str = Field(unique=True, index=True)
    mv_uuid: str | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)


class Clip(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    moment_id: str = Field(unique=True, index=True)
    map_name: str | None = None
    title: str = ""
    local_path: str | None = None
    size_bytes: int | None = None
    push_status: str = "none"  # none/pushed/degraded_to_card/failed
    mv_uuid: str | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)


class SeasonStats(SQLModel, table=True):
    """赛季统计快照（detailStats data 全量 JSON，趋势图/雷达/热图数据源）。"""
    id: int | None = Field(default=None, primary_key=True)
    season_id: str = Field(index=True)  # 平台 seasonId（recent 时存实际返回值）
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)
