from fastapi import APIRouter, HTTPException

from ..database import SessionDep
from ..models import Task
from ..services import task_manager
from .auth_api import CurrentUser

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _scoped_tasks(session, user):
    """admin 看全部任务；普通用户只看自己的任务。"""
    from sqlmodel import select

    stmt = select(Task).order_by(Task.created_at.desc())
    if not user.is_admin:
        stmt = stmt.where(Task.user_id == user.id)
    return session.exec(stmt).all()


@router.post("", status_code=202)
def create_task(body: dict, session: SessionDep, user: CurrentUser) -> dict:
    try:
        task = task_manager.create_task(
            session, body.get("type", ""), body.get("payload") or {}, int(body.get("priority", 5)), user_id=user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": task.id, "status": task.status}


@router.get("")
def list_tasks(session: SessionDep, user: CurrentUser) -> list[dict]:
    return [
        {
            "id": t.id,
            "type": t.type,
            "payload": t.payload,
            "status": t.status,
            "priority": t.priority,
            "progress": t.progress,
            "result": t.result,
            "error": t.error,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in _scoped_tasks(session, user)
    ]


@router.get("/{task_id}")
def get_task(task_id: int, session: SessionDep, user: CurrentUser) -> dict:
    task = _owned_task(session, task_id, user)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "id": task.id,
        "type": task.type,
        "payload": task.payload,
        "status": task.status,
        "priority": task.priority,
        "progress": task.progress,
        "result": task.result,
        "error": task.error,
    }


@router.post("/{task_id}/run")
async def run_task(task_id: int, session: SessionDep) -> dict:
    from ..models import Task

    if session.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    task = await task_manager.run_task(task_id)
    return {"id": task.id, "status": task.status, "error": task.error}


def _owned_task(session, task_id: int, user):
    """普通用户只能读写自己的任务；admin 全量。legacy（user_id=None）仅 admin 可见（与 matches 口径一致）。"""
    task = session.get(Task, task_id)
    if task is None:
        return None
    if not user.is_admin and task.user_id != user.id:
        return None
    return task
