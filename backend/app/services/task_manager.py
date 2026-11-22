"""任务中心：priority 调度、状态机、NEED_AUTH 熔断（完美平台 401/403 场景）。"""
from __future__ import annotations

import inspect
from typing import Awaitable, Callable

from loguru import logger
from sqlmodel import Session, select

from ..database import session_factory
from ..models import Task, utcnow
from .wanmei import WanmeiAuthError  # 单一定义源：完美平台 401/403 熔断异常（re-export）

Handler = Callable[[Task, Callable[[], Session]], Awaitable[dict]]

HANDLERS: dict[str, Handler] = {}


def create_task(
    session: Session, type_: str, payload: dict | None = None, priority: int = 5
) -> Task:
    if type_ not in HANDLERS:
        raise ValueError(f"未知任务类型：{type_}")
    task = Task(type=type_, payload=payload or {}, priority=priority)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def _save(task: Task, session: Session) -> None:
    task.updated_at = utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)


async def run_task(task_id: int) -> Task:
    """执行单个任务；WanmeiAuthError → NEED_AUTH（熔断），其余异常 → failed。"""
    with session_factory() as session:
        task = session.get(Task, task_id)
        if task is None:
            raise ValueError(f"任务不存在：{task_id}")
        task.status = "running"
        _save(task, session)
        handler = HANDLERS.get(task.type)
        try:
            if handler is None:
                raise ValueError(f"任务类型未注册 handler：{task.type}")
            result = handler(task, session_factory)
            if inspect.isawaitable(result):
                result = await result
            task.status = "success"
            task.result = result
            task.progress = 1.0
            logger.info(f"[任务] id={task.id} type={task.type} 执行成功")
        except WanmeiAuthError as exc:
            task.status = "NEED_AUTH"
            task.error = f"token 失效，需人工更新凭证：{exc}"
            logger.warning(f"[任务] id={task.id} type={task.type} NEED_AUTH 熔断")
        except Exception as exc:  # noqa: BLE001
            task.status = "failed"
            task.error = str(exc)
            logger.exception(f"[任务] id={task.id} type={task.type} 执行失败")
        _save(task, session)
        return task


def list_tasks(session: Session) -> list[Task]:
    stmt = select(Task).order_by(Task.priority, Task.created_at.desc())
    return list(session.exec(stmt).all())
