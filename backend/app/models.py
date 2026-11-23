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
    detail_json: dict | None = Field(default=None, sa_column=Column(JSON))  # v1 全场详细数据缓存


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
    mv_uuid: str | None = None  # MindVault 总结笔记（重学走更新不重复建）
    raw: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)


class VideoSummary(SQLModel, table=True):
    """视频 AI 总结本地存档（2026-11-23 grill-me 决策 A：CS2HQ 自站可看，不依赖 MV 在线）。"""

    id: int | None = Field(default=None, primary_key=True)
    bvid: str = Field(unique=True, index=True)
    summary_md: str = ""
    model: str | None = None  # 生成总结的模型名（排障用）
    created_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)


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
    zone: str | None = Field(default=None, index=True)  # A区/B区/中路/出生点（AI 输出，前端正则兜底）
    favorited: bool = Field(default=False)  # 用户收藏（★），列表收藏置顶
    created_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)


class GrenadeCardImage(SQLModel, table=True):
    """道具卡贴图（用户手传，grill-me v2 决策 1a：文件落 data/uploads/{card_id}/）。"""

    id: int | None = Field(default=None, primary_key=True)
    card_id: int = Field(index=True, foreign_key="grenadecard.id")
    filename: str = ""  # 服务端 uuid 命名
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


class ChatSession(SQLModel, table=True):
    """AI 教练对话会话（多轮，历史持久化）。"""
    id: int | None = Field(default=None, primary_key=True)
    title: str = "新对话"
    import_key: str | None = Field(default=None, index=True)  # 外部导入幂等键（如 DeepSeek 分享 id）
    created_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)


class ChatMessage(SQLModel, table=True):
    """对话消息（role: user/assistant）。"""
    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(index=True, foreign_key="chatsession.id")
    role: str
    content: str
    image_ids: str | None = Field(default=None, index=True)  # JSON 数组字符串，如 "[1,2]"
    created_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)


class ChatImage(SQLModel, table=True):
    """AI 教练对话图片（OCR 间接路线：落盘 + 识别文本，供上下文注入与前端展示）。"""
    id: int | None = Field(default=None, primary_key=True)
    session_id: int | None = Field(default=None, index=True)  # 上传时可未绑定，发消息时绑定
    filename: str  # data/uploads/chat/{id}/{filename}
    ocr_text: str = ""  # RapidOCR 识别文本（AI 以文字间接看图）
    created_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)


class TrainingCard(SQLModel, table=True):
    """训练处方卡（教练回复的 ```training 块解析产物）：一键入任务中心打卡。"""
    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(index=True, foreign_key="chatsession.id")
    title: str
    detail: str = ""
    duration_min: int | None = None  # 建议时长（分钟）
    check: str = ""  # 验收标准（如「爆头击杀 200」）
    content_hash: str = Field(unique=True, index=True)  # title+detail+check 去重键
    task_id: int | None = Field(default=None, index=True)  # 入任务中心后的 Task.id
    created_at: datetime = Field(default_factory=utcnow, sa_type=NAIVE_DT)
