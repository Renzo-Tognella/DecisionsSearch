from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decisionssearch.application.jobs.daily_scan_service import DailyScanService, DailyScanResult


class TestDailyScanResult:
    def test_defaults(self):
        r = DailyScanResult()
        assert r.prs_scanned == 0
        assert r.prs_new == 0
        assert r.cards_scanned == 0
        assert r.errors == []


class TestDailyScanService:
    @pytest.mark.asyncio
    async def test_scan_with_no_config(self):
        svc = DailyScanService()
        result = await svc.run_scan()
        assert result.prs_scanned == 0
        assert result.cards_scanned == 0

    @pytest.mark.asyncio
    async def test_scan_github_no_repos(self):
        svc = DailyScanService(config={"repos": []})
        result = await svc.run_scan()
        assert result.prs_scanned == 0

    @pytest.mark.asyncio
    async def test_scan_shortcut_no_token(self):
        svc = DailyScanService(config={"repos": [], "shortcut_token": ""})
        result = await svc.run_scan()
        assert result.cards_scanned == 0

    @pytest.mark.asyncio
    async def test_scan_github_prs_success(self):
        container = MagicMock()
        pr_memory = AsyncMock()
        pr_memory.create_pr_memory.return_value = {"memory_id": "abc"}
        container.pr_memory = pr_memory

        svc = DailyScanService(
            container=container,
            config={"repos": ["org/repo"], "project": "TEST"},
        )

        pr_data = [{
            "number": 42,
            "title": "Fix bug",
            "body": "fixes stuff",
            "headRefName": "fix/bug",
            "baseRefName": "main",
            "url": "https://github.com/org/repo/pull/42",
            "mergedAt": "",
            "createdAt": "2026-04-26T10:00:00Z",
            "state": "OPEN",
            "author": {"login": "dev"},
            "labels": [],
        }]

        with patch.object(svc, "_fetch_github_prs", return_value=pr_data):
            with patch.object(svc, "_fetch_pr_files", return_value=["app.py"]):
                result = await svc.run_scan()

        assert result.prs_scanned == 1
        assert result.prs_new == 1

    @pytest.mark.asyncio
    async def test_scan_github_failure_graceful(self):
        svc = DailyScanService(config={"repos": ["org/repo"]})

        with patch.object(svc, "_fetch_github_prs", side_effect=RuntimeError("gh not found")):
            result = await svc.run_scan()

        assert len(result.errors) == 1
        assert "gh not found" in result.errors[0]
