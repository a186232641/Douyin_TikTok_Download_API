from fastapi import APIRouter, HTTPException

from app.api import task_queue

router = APIRouter()


@router.get("/task/{task_id}", summary="查询任务状态/Query task status")
async def get_task(task_id: str):
    """根据 task_id 查询异步任务的状态、进度、结果。"""
    task = task_queue.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    return task.to_dict()


@router.get("/tasks", summary="列出全部任务/List all tasks")
async def list_tasks(status: str = None, kind: str = None, limit: int = 100):
    """列出内存中（含从盘恢复的）全部任务，可按 status/kind 过滤。"""
    tasks = task_queue.list_all()
    if status:
        tasks = [t for t in tasks if t.status.value == status]
    if kind:
        tasks = [t for t in tasks if t.kind == kind]
    tasks.sort(key=lambda t: t.created_at, reverse=True)
    return {"total": len(tasks), "tasks": [t.to_dict() for t in tasks[:limit]]}
