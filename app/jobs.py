"""งานเบื้องหลังแบบเก็บในหน่วยความจำ ใช้รายงานความคืบหน้าให้หน้าเว็บ"""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

JOB_TTL_SECONDS = 60 * 60


@dataclass
class Job:
    id: str
    status: str = "running"  # running | done | error
    stage: str = ""
    progress: float = 0.0  # 0-100
    result: dict = field(default_factory=dict)
    audio: bytes | None = None
    error: str = ""
    created: float = field(default_factory=time.time)

    def update(self, stage: str, progress: float) -> None:
        self.stage = stage
        self.progress = max(self.progress, min(progress, 100.0))

    def public(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "stage": self.stage,
            "progress": round(self.progress),
            "error": self.error,
            "result": self.result,
        }


_jobs: dict[str, Job] = {}
_tasks: set[asyncio.Task] = set()


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def start(work: Callable[[Job], Awaitable[None]]) -> Job:
    _cleanup()
    job = Job(id=uuid.uuid4().hex)
    _jobs[job.id] = job

    async def run():
        try:
            await work(job)
            job.progress = 100.0
            job.status = "done"
        except Exception as exc:
            job.error = str(exc) or type(exc).__name__
            job.status = "error"

    task = asyncio.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job


def _cleanup() -> None:
    cutoff = time.time() - JOB_TTL_SECONDS
    for job_id in [j.id for j in _jobs.values() if j.created < cutoff]:
        del _jobs[job_id]
