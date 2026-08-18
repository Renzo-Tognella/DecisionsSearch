from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from decisionssearch.domain.shared.job_status import JobRun, JobDefinition

logger = logging.getLogger(__name__)


@dataclass
class SchedulerService:
    container: Any = None
    config: dict = field(default_factory=dict)
    _scheduler: AsyncIOScheduler | None = field(default=None, init=False)
    _job_runs: dict[str, list[JobRun]] = field(default_factory=dict, init=False)
    _job_defs: dict[str, JobDefinition] = field(default_factory=dict, init=False)

    def _build_jobstore(self):
        persistence = self.config.get("persistence", "memory")
        if persistence == "sqlite":
            try:
                from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
                path = self.config.get("sqlite_path", "data/scheduler.db")
                return {"default": SQLAlchemyJobStore(url=f"sqlite:///{path}")}
            except ImportError:
                logger.warning("sqlalchemy not installed — falling back to memory jobstore")
        return {"default": MemoryJobStore()}

    async def start(self) -> None:
        jobstores = self._build_jobstore()
        self._scheduler = AsyncIOScheduler(jobstores=jobstores, timezone="UTC")
        self._register_jobs()
        self._scheduler.add_listener(self._on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        self._scheduler.start()
        logger.info("Scheduler started with %d jobs", len(self._job_defs))

    async def stop(self) -> None:
        if self._scheduler:
            self._scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped")

    def _register_jobs(self) -> None:
        jobs_cfg = self.config.get("jobs", {
            "daily_consolidation": "0 3 * * *",
            "daily_summary": "0 4 * * *",
        })
        for job_name, cron_expr in jobs_cfg.items():
            parts = cron_expr.split()
            trigger = CronTrigger(
                minute=parts[0] if len(parts) > 0 else "0",
                hour=parts[1] if len(parts) > 1 else "*",
                day=parts[2] if len(parts) > 2 else "*",
                month=parts[3] if len(parts) > 3 else "*",
                day_of_week=parts[4] if len(parts) > 4 else "*",
            )
            self._scheduler.add_job(
                _run_job, trigger,
                id=job_name, name=job_name,
                replace_existing=True, max_instances=1,
                kwargs={"service": self, "job_name": job_name},
            )
            self._job_defs[job_name] = JobDefinition(
                name=job_name, trigger_type="cron", trigger_value=cron_expr,
            )

    async def _on_job_event(self, event) -> None:
        job_id = getattr(event, "job_id", "unknown")
        if event.code == EVENT_JOB_EXECUTED:
            logger.info("Job %s completed", job_id)
        elif event.code == EVENT_JOB_ERROR:
            logger.error("Job %s failed: %s", job_id, getattr(event, "exception", "unknown"))

    async def _execute_job(self, job_name: str) -> dict:
        if job_name == "daily_consolidation":
            if self.container and hasattr(self.container, "consolidation") and self.container.consolidation:
                result = await self.container.consolidation.run_now(scope="all")
                return {"items_processed": str(result)}
            return {"status": "no_consolidation_service"}
        elif job_name == "daily_summary":
            return {"status": "no_summary_service_yet"}
        elif job_name == "daily_scan":
            return await self._run_daily_scan()
        return {"status": "unknown_job"}

    async def _run_daily_scan(self) -> dict:
        if not self.container or not hasattr(self.container, "daily_scan"):
            return {"status": "no_daily_scan_service"}
        result = await self.container.daily_scan.run_scan()
        return {
            "prs_scanned": result.prs_scanned,
            "prs_new": result.prs_new,
            "cards_scanned": result.cards_scanned,
            "cards_new": result.cards_new,
            "errors": result.errors,
        }

    async def run_startup_jobs(self) -> None:
        startup_jobs = self.config.get("run_on_startup", [])
        for job_name in startup_jobs:
            logger.info("Running startup job: %s", job_name)
            try:
                await self.run_job_now(job_name)
            except Exception as e:
                logger.error("Startup job %s failed: %s", job_name, e)

    async def run_job_now(self, job_name: str) -> JobRun:
        run = JobRun(job_name=job_name, status="running")
        self._job_runs.setdefault(job_name, []).append(run)
        try:
            run.result_summary = await self._execute_job(job_name)
            run.status = "completed"
        except Exception as e:
            run.status = "failed"
            run.error = str(e)
        run.completed_at = str(__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat())
        return run

    def list_jobs(self) -> list[dict]:
        result = []
        for name, defn in self._job_defs.items():
            job = self._scheduler.get_job(name) if self._scheduler else None
            result.append({
                "name": name,
                "trigger_type": defn.trigger_type,
                "trigger_value": defn.trigger_value,
                "next_run": str(job.next_run_time) if job and job.next_run_time else None,
                "is_paused": bool(job.next_run_time is None) if job else False,
            })
        return result

    def get_job_history(self, job_name: str, limit: int = 20) -> list[dict]:
        runs = self._job_runs.get(job_name, [])
        return [
            {
                "run_id": r.run_id, "started_at": r.started_at,
                "completed_at": r.completed_at, "status": r.status,
                "error": r.error,
            }
            for r in runs[-limit:]
        ]


async def _run_job(service: SchedulerService, job_name: str) -> dict:
    return await service.run_job_now(job_name)
