"""训练处方打卡任务：run 即 success（教练处方由用户线下执行，此处只做记录）。"""
from __future__ import annotations

from typing import Callable

from loguru import logger
from sqlmodel import Session

from ..models import Task


async def training_practice_handler(task: Task, session_factory_fn: Callable[[], Session]) -> dict:
    """打卡语义：任务即训练项，run = 用户确认完成；payload 原样落 result 供周报/任务中心展示。"""
    payload = task.payload if isinstance(task.payload, dict) else {}
    title = payload.get("title", "训练处方")
    logger.info(f"[训练处方] 打卡完成：{title}（card={payload.get('card_id')}）")
    return {"completed": True, "title": title, "check": payload.get("check", ""), "card_id": payload.get("card_id")}


def register() -> None:
    from . import task_manager

    task_manager.HANDLERS["training_practice"] = training_practice_handler
