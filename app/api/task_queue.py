"""异步任务队列：单 worker 串行消费，对出站抖音 API 限速。

设计要点：
- 单进程内存队列 + 1 个 worker（并发=1），避免触发抖音 Cookie 风控
- RateLimiter 强制两次出站 API 调用之间最小 5s 间隔（±30% 抖动）
- 任务状态每次变化都落盘到 downloads/_tasks/<id>.json，进程重启后可继续查询
- 进程重启时运行中的任务会被标记为 FAILED（无法续传）
"""

import asyncio
import glob
import json
import os
import random
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from crawlers.utils.logger import logger

# 任务状态文件存放在下载根目录之外，避免被「上传 downloads/* 到 OSS」的脚本误传
TASKS_DIR = os.path.join("var", "tasks")

# 限速参数（与设计文档一致）
RATE_INTERVAL_SECONDS = 5.0
RATE_JITTER = 0.3


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class Task:
    id: str
    kind: str
    params: dict
    status: TaskStatus = TaskStatus.QUEUED
    progress: dict = field(default_factory=dict)
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


class RateLimiter:
    """串行限速器：保证两次 acquire() 之间至少间隔 interval 秒（带 ±jitter 抖动）。"""

    def __init__(self, interval: float, jitter: float = 0.3):
        self.interval = interval
        self.jitter = jitter
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                await asyncio.sleep(wait)
            factor = 1.0 + random.uniform(-self.jitter, self.jitter)
            self._next_allowed = time.monotonic() + max(0.1, self.interval * factor)


# ---- 模块级单例 ----
_queue: Optional[asyncio.Queue] = None
_tasks: Dict[str, Task] = {}
_worker_task: Optional[asyncio.Task] = None
_rate_limiter = RateLimiter(interval=RATE_INTERVAL_SECONDS, jitter=RATE_JITTER)


# 类型别名：任务执行函数 (task, limiter) -> result_dict
Runner = Callable[[Task, RateLimiter], Awaitable[dict]]


def _ensure_queue() -> asyncio.Queue:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


def _persist(task: Task) -> None:
    os.makedirs(TASKS_DIR, exist_ok=True)
    path = os.path.join(TASKS_DIR, f"{task.id}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(task.to_dict(), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def submit(kind: str, params: dict, runner: Runner) -> Task:
    """投递任务到队列，立即返回 Task 对象（status=queued）。"""
    queue = _ensure_queue()
    task = Task(id=uuid.uuid4().hex[:12], kind=kind, params=params)
    _tasks[task.id] = task
    _persist(task)
    queue.put_nowait((task, runner))
    logger.info(f"[task_queue] 任务已入队: {task.id} kind={kind} qsize={queue.qsize()}")
    return task


def get(task_id: str) -> Optional[Task]:
    return _tasks.get(task_id)


def list_all() -> List[Task]:
    return list(_tasks.values())


def update_progress(task: Task, progress: dict) -> None:
    task.progress = progress
    _persist(task)


def _classify_final_status(stats: Any) -> TaskStatus:
    if not isinstance(stats, dict):
        return TaskStatus.SUCCESS
    failed = stats.get("failed", 0)
    success = stats.get("success", 0)
    if failed > 0 and success > 0:
        return TaskStatus.PARTIAL
    if failed > 0 and success == 0:
        return TaskStatus.FAILED
    return TaskStatus.SUCCESS


def _load_existing_tasks() -> None:
    """启动时从盘恢复任务到内存，把运行中的标为 FAILED（进程重启中断）。"""
    if not os.path.isdir(TASKS_DIR):
        return
    for path in glob.glob(os.path.join(TASKS_DIR, "*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            status_str = data.get("status", TaskStatus.FAILED.value)
            try:
                status = TaskStatus(status_str)
            except ValueError:
                status = TaskStatus.FAILED
            task = Task(
                id=data["id"],
                kind=data.get("kind", "unknown"),
                params=data.get("params", {}),
                status=status,
                progress=data.get("progress", {}),
                result=data.get("result"),
                error=data.get("error"),
                created_at=data.get("created_at") or datetime.utcnow().isoformat() + "Z",
                started_at=data.get("started_at"),
                finished_at=data.get("finished_at"),
            )
            if task.status in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                task.status = TaskStatus.FAILED
                task.error = "进程重启时中断，无法续传"
                task.finished_at = datetime.utcnow().isoformat() + "Z"
                _persist(task)
            _tasks[task.id] = task
        except Exception as e:
            logger.warning(f"[task_queue] 恢复任务文件失败 {path}: {e}")
    if _tasks:
        logger.info(f"[task_queue] 从盘恢复 {len(_tasks)} 个历史任务")


async def _worker_loop() -> None:
    queue = _ensure_queue()
    logger.info("[task_queue] worker 已启动 (concurrency=1, interval=%.1fs)" % RATE_INTERVAL_SECONDS)
    while True:
        task, runner = await queue.get()
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow().isoformat() + "Z"
        _persist(task)
        logger.info(f"[task_queue] 开始执行: {task.id} ({task.kind})")
        try:
            result = await runner(task, _rate_limiter)
            task.result = result if isinstance(result, dict) else {"value": result}
            task.status = _classify_final_status(result)
        except asyncio.CancelledError:
            task.status = TaskStatus.FAILED
            task.error = "任务被取消（worker 关闭）"
            _persist(task)
            raise
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = f"{type(e).__name__}: {e}"
            logger.exception(f"[task_queue] 任务执行失败: {task.id}")
        finally:
            task.finished_at = datetime.utcnow().isoformat() + "Z"
            _persist(task)
            queue.task_done()
            logger.info(
                f"[task_queue] 任务完成: {task.id} status={task.status.value}"
            )


async def start_worker() -> None:
    global _worker_task
    _ensure_queue()
    _load_existing_tasks()
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop(), name="task_queue_worker")


async def stop_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
        logger.info("[task_queue] worker 已停止")
