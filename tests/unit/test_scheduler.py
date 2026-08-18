from __future__ import annotations

import pytest
from decisionssearch.application.jobs.scheduler_service import SchedulerService


class TestSchedulerService:
    @pytest.mark.asyncio
    async def test_scheduler_start_stop(self):
        svc = SchedulerService()
        await svc.start()
        assert svc._scheduler is not None
        assert svc._scheduler.running
        await svc.stop()

    @pytest.mark.asyncio
    async def test_list_jobs(self):
        svc = SchedulerService()
        await svc.start()
        jobs = svc.list_jobs()
        await svc.stop()
        assert len(jobs) == 2
        names = {j["name"] for j in jobs}
        assert "daily_consolidation" in names
        assert "daily_summary" in names

    @pytest.mark.asyncio
    async def test_run_job_now(self):
        svc = SchedulerService()
        await svc.start()
        run = await svc.run_job_now("daily_consolidation")
        await svc.stop()
        assert run.status in ("completed", "failed")
        assert run.job_name == "daily_consolidation"

    @pytest.mark.asyncio
    async def test_custom_config(self):
        svc = SchedulerService(config={
            "persistence": "memory",
            "jobs": {"cleanup": "0 5 * * *"},
        })
        await svc.start()
        jobs = svc.list_jobs()
        await svc.stop()
        assert len(jobs) == 1
        assert jobs[0]["name"] == "cleanup"

    @pytest.mark.asyncio
    async def test_job_history(self):
        svc = SchedulerService()
        await svc.start()
        await svc.run_job_now("daily_consolidation")
        history = svc.get_job_history("daily_consolidation")
        await svc.stop()
        assert len(history) == 1
        assert history[0]["status"] in ("completed", "failed")
