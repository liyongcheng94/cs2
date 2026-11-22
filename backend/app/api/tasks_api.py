from fastapi import APIRouter, HTTPException

from ..database import SessionDep
from ..services import task_manager

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=202)
def create_task(body: dict, session: SessionDep) -> dict:
    try:
        task = task_manager.create_task(
            session, body.get("type", ""), body.get("payload") or {}, int(body.get("priority", 5))
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": task.id, "status": task.status}


@router.get("")
def list_tasks(session: SessionDep) -> list[dict]:
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
        for t in task_manager.list_tasks(session)
    ]


@router.get("/{task_id}")
def get_task(task_id: int, session: SessionDep) -> dict:
    from ..models import Task

    task = session.get(Task, task_id)
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
