"""AI 复盘生成：ReviewOutput 护栏（重试1次→纯文本降级）+ Rule-based 唯一重点双轨制 + 幂等 hash。"""
from __future__ import annotations

import hashlib
import json
import re
from typing import NamedTuple

from loguru import logger
from pydantic import ValidationError

from ..schemas.analysis import FourDimAnalysis, ReviewOutput
from .ai_client import AiClient, AiError, load_prompt

PROMPT_VERSION = PromptVersion = "v1"

# Rule-based 硬红线（评审确定的双轨制：触发即强制，AI 不自由发挥）
NEAR_RANGE_REDLINE = 0.30  # 0-5m 对枪胜率低于 30%
FULL_BUY_LOSE_REDLINE = 0.50  # 满编局败率高于 50%（资源转化差）
UTILITY_WASTE_REDLINE = 0.35  # 道具浪费率高于 35%
DISADVANTAGED_REDLINE = 0.40  # 劣势枪位死亡率高于 40%


def compute_source_hash(match_id: str, prompt_version: str) -> str:
    """幂等键：matchId + prompt_version（提示词迭代后生成 v2 新笔记保留轨迹）。"""
    return hashlib.sha256(f"{match_id}+{prompt_version}".encode()).hexdigest()


def rule_based_focus(analysis: FourDimAnalysis) -> str | None:
    """硬红线优先：命中即返回固定行动指令；无红线返回 None（交 AI 在证据链内选择）。"""
    for b in analysis.duels.by_weapon_distance:
        # 样本 <3 的格子（0/1→0%）属统计噪音，不触发硬红线
        n = (b.kills or 0) + (b.deaths or 0)
        if b.distance == "0-5m" and b.win_rate is not None and n >= 3 and b.win_rate < NEAR_RANGE_REDLINE:
            return "近战急停：aim_botz 移动急停开枪 10 分钟，只打两发就停"
    if analysis.economy.full_buy_lose_rate is not None and analysis.economy.full_buy_lose_rate > FULL_BUY_LOSE_REDLINE:
        return "资源转化：满编局打不出优势——复盘每个满编回合的首个交火点，避免单人无信息探点"
    if analysis.utility.waste_rate is not None and analysis.utility.waste_rate > UTILITY_WASTE_REDLINE:
        return "道具专项：主图 3 个固定道具各练 5 次，直到 100% 成功"
    if analysis.deaths.disadvantaged_rate is not None and analysis.deaths.disadvantaged_rate > DISADVANTAGED_REDLINE:
        return "身位管理：复盘每场死亡位置，减少无掩体/交叉火力下的暴露"
    return None


def _strip_json_block(text: str) -> str:
    """从模型输出中剥出 JSON（容忍 ```json 包裹与前后闲话）。"""
    m = re.search(r"\{.*\}", text, re.S)
    return m.group(0) if m else text


class ReportResult(NamedTuple):
    review: ReviewOutput | None
    markdown: str
    degraded: bool


async def _ai_review(analysis: FourDimAnalysis, ai: AiClient, focus: str | None) -> ReviewOutput:
    system = load_prompt("review") or (
        "你是 CS2 复盘教练。只输出 JSON（ReviewOutput 结构）："
        '{"match_id":str,"mistakes":[{"title","evidence","severity":"high|mid|low"}],"highlights":[str],'
        '"today_focus":str,"tomorrow":[str]}。'
        "pistol_rounds 字段是第 1/13 回合手枪局结果（MR12，全队起手枪）：my_side/won 分回合、t_*/ct_* 分阵营聚合。"
        "T 方手枪局连败时必须作为失误候选（团队执行问题，不是个人枪法）；evidence 引用具体回合的 my_side/won 取值。"
        "口径注意：utility.waste_rate 是「闪光效率浪费」（样本<3 的对枪矩阵格子——如 0/1 的 0% 或 1/1 的 100%——是统计噪音，不足以下结论，不得作为失误证据引入（扔了没致盲人≥0.5s），不要与道具买而不扔（usage[].waste_rate）混用。"
        "防幻觉铁律：每条失误的 evidence 必须引用我给你的 JSON 数据里的具体字段与取值；"
        "没有数据支撑就宁可输出空 mistakes（'无明显失误'），严禁臆造因果。"
        "today_focus 从 top3 里只选一个最影响胜率的问题，输出一句具体行动指令。"
    )
    user = json.dumps(analysis.model_dump(), ensure_ascii=False)
    if focus:
        user += f"\n\n[今日唯一重点已被硬红线锁定，直接采用]：{focus}"
    raw = await ai.chat(system, user)
    data = json.loads(_strip_json_block(raw))
    if focus:
        data["today_focus"] = focus  # 硬红线覆盖
    data.setdefault("match_id", analysis.match_id)
    return ReviewOutput(**data)


def _fallback_markdown(analysis: FourDimAnalysis, reason: str) -> str:
    d = analysis.model_dump()
    lines = [
        f"# 复盘（数据直读·AI降级）· {analysis.match_id}",
        "",
        f"> ⚠️ AI 复盘未通过校验，已降级为纯数据复盘。原因：{reason}",
        "",
        "## 对枪矩阵",
        "```",
        json.dumps(d["duels"], ensure_ascii=False, indent=1),
        "```",
        "## 死亡还原",
        "```",
        json.dumps(d["deaths"], ensure_ascii=False, indent=1),
        "```",
        "## 经济与道具",
        "```",
        json.dumps(d["economy"], ensure_ascii=False, indent=1),
        json.dumps(d["utility"], ensure_ascii=False, indent=1),
        "```",
        "## 今日唯一重点",
        rule_based_focus(analysis) or "（无硬红线；AI 恢复后生成）",
    ]
    return "\n".join(lines)


async def build_report(
    analysis: FourDimAnalysis,
    ai: AiClient | None = None,
    focus: str | None = None,
    max_attempts: int = 2,
) -> ReportResult:
    """护栏：合法 JSON → ReviewOutput；非法重试1次 → 仍非法降级纯文本（degraded=True）。"""
    focus = focus or rule_based_focus(analysis)
    if ai is None:
        return ReportResult(None, _fallback_markdown(analysis, "未配置 AI"), degraded=True)
    last_err = ""
    for attempt in range(1, max_attempts + 1):
        try:
            review = await _ai_review(analysis, ai, focus)
            md = render_markdown(review, analysis)
            return ReportResult(review, md, degraded=False)
        except (AiError, json.JSONDecodeError, ValidationError) as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            logger.warning(f"[AI复盘] {analysis.match_id} 第{attempt}次尝试失败：{last_err}")
    return ReportResult(None, _fallback_markdown(analysis, last_err), degraded=True)


def render_markdown(review: ReviewOutput, analysis: FourDimAnalysis) -> str:
    """复盘 Markdown：失误/高光/今日唯一重点/明日清单 + 证据链内联。"""
    lines = [f"# 复盘 · {analysis.match_id}（{analysis.meta.parser}）", ""]
    lines.append("## 失误 Top3")
    for i, m in enumerate(review.mistakes[:3], 1):
        sev = f"（{m.severity}）" if m.severity else ""
        lines.append(f"{i}. **{m.title}**{sev} —— 证据：`{m.evidence}`")
    if not review.mistakes:
        lines.append("- 无明显失误（数据无支撑，按防幻觉铁律不臆造）")
    lines.append("")
    lines.append("## 高光")
    if review.highlights:
        lines += [f"- {h}" for h in review.highlights]
    else:
        lines.append("- （无）")
    lines += ["", "## 今日唯一重点", review.today_focus or "（AI 未给出）"]
    lines.append("")
    lines.append("## 明日练什么")
    if review.tomorrow:
        lines += [f"- {t}" for t in review.tomorrow]
    else:
        lines.append("- （无）")
    lines += ["", "---", f"*CS2HQ 自动复盘 · prompt {PROMPT_VERSION} · schema {analysis.schema_version}*"]
    return "\n".join(lines)
