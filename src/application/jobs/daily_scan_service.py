from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DailyScanResult:
    prs_scanned: int = 0
    prs_new: int = 0
    cards_scanned: int = 0
    cards_new: int = 0
    errors: list[str] = field(default_factory=list)


class DailyScanService:
    def __init__(self, container: Any = None, config: dict | None = None):
        self.container = container
        self.config = config or {}
        self._gh_token = self.config.get("github_token", "") or os.environ.get("GITHUB_TOKEN", "")
        self._shortcut_token = self.config.get("shortcut_token", "") or os.environ.get("SHORTCUT_TOKEN", "")
        self._repos: list[str] = self.config.get("repos", [])
        self._shortcut_teams: list[str] = self.config.get("shortcut_teams", [])
        self._project: str = self.config.get("project", "CORE")

    async def run_scan(self, full: bool = False) -> DailyScanResult:
        result = DailyScanResult()
        if full:
            since = "2000-01-01T00:00:00Z"
        else:
            since = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")

        result = await self._scan_github_prs(since, result)
        result = await self._scan_shortcut_cards(since, result)

        logger.info(
            "Daily scan complete: %d PRs (%d new), %d cards (%d new)",
            result.prs_scanned, result.prs_new,
            result.cards_scanned, result.cards_new,
        )
        return result

    async def _scan_github_prs(self, since: str, result: DailyScanResult) -> DailyScanResult:
        for repo in self._repos:
            try:
                prs = await self._fetch_github_prs(repo, since)
                result.prs_scanned += len(prs)
                for pr in prs:
                    created = await self._ingest_pr(pr, repo)
                    if created:
                        result.prs_new += 1
            except Exception as e:
                msg = f"GitHub scan failed for {repo}: {e}"
                logger.exception(msg)
                result.errors.append(msg)
        return result

    async def _fetch_github_prs(self, repo: str, since: str) -> list[dict]:
        cmd = [
            "gh", "pr", "list",
            "--repo", repo,
            "--state", "all",
            "--search", f"created:>={since[:10]}",
            "--json", "number,title,body,headRefName,baseRefName,url,mergedAt,createdAt,state,author,labels",
            "--limit", "50",
        ]
        env = {**os.environ}
        if self._gh_token:
            env["GH_TOKEN"] = self._gh_token

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=env,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"gh pr list failed: {stderr.decode()[:500]}")

        return json.loads(stdout.decode())

    async def _ingest_pr(self, pr: dict, repo: str) -> bool:
        if not self.container or not hasattr(self.container, "pr_memory"):
            return False

        from decisionssearch.domain import CreatePRMemoryCommand

        pr_number = pr.get("number", 0)
        author = pr.get("author", {})
        author_login = author.get("login", "") if isinstance(author, dict) else str(author)
        labels = [label.get("name", "") for label in pr.get("labels", []) if isinstance(label, dict)]
        changed_files = await self._fetch_pr_files(repo, pr_number)

        command = CreatePRMemoryCommand(
            project=self._project,
            repo=repo,
            pr_number=pr_number,
            title=pr.get("title", ""),
            summary=(pr.get("body") or "Auto-scanned PR")[:2000],
            changed_files=changed_files,
            pr_url=pr.get("url", ""),
            branch=pr.get("headRefName", ""),
            work_item_url=pr.get("url", ""),
            authors=[author_login],
            areas=labels,
            status="merged" if pr.get("mergedAt") else pr.get("state", "open").lower(),
            merged_at=pr.get("mergedAt", ""),
            event_date=pr.get("createdAt", ""),
        )
        try:
            await self.container.pr_memory.create_pr_memory(command)
            return True
        except Exception as e:
            logger.warning("Failed to ingest PR #%d from %s: %s", pr_number, repo, e)
            return False

    async def _fetch_pr_files(self, repo: str, pr_number: int) -> list[str]:
        cmd = [
            "gh", "pr", "diff", str(pr_number),
            "--repo", repo, "--name-only",
        ]
        env = {**os.environ}
        if self._gh_token:
            env["GH_TOKEN"] = self._gh_token

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=env,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            return [f.strip() for f in stdout.decode().strip().split("\n") if f.strip()]
        except Exception:
            return []

    async def _scan_shortcut_cards(self, since: str, result: DailyScanResult) -> DailyScanResult:
        if not self._shortcut_token:
            return result

        try:
            import httpx
        except ImportError:
            return result

        since_date = since[:10]
        headers = {"Shortcut-Token": self._shortcut_token}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                url = "https://api.app.shortcut.com/api/v3/stories"
                params = {
                    "includes": "true",
                    "page_size": 50,
                    "query": f"updated:{since_date}",
                }
                if self._shortcut_teams:
                    params["team_id"] = ",".join(self._shortcut_teams)

                resp = await client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                stories = resp.json()

                if isinstance(stories, dict):
                    stories = stories.get("data", stories.get("stories", []))

                result.cards_scanned = len(stories)
                for story in stories:
                    created = await self._ingest_shortcut_card(story)
                    if created:
                        result.cards_new += 1
        except Exception as e:
            msg = f"Shortcut scan failed: {e}"
            logger.exception(msg)
            result.errors.append(msg)

        return result

    async def _ingest_shortcut_card(self, story: dict) -> bool:
        if not self.container or not hasattr(self.container, "agent_loop"):
            return False

        story_id = story.get("id", "")
        story_type = story.get("story_type", "feature")
        name = story.get("name", "")
        description = story.get("description", "") or ""
        workflow_state = story.get("workflow_state", {})
        state_name = workflow_state.get("name", "") if isinstance(workflow_state, dict) else ""
        labels = [label.get("name", "") for label in story.get("labels", []) if isinstance(label, dict)]
        url = story.get("app_url", "")

        content = f"Shortcut Card #{story_id}: {name}\n"
        content += f"Type: {story_type} | State: {state_name}\n"
        if description:
            content += f"Description: {description[:500]}\n"
        if labels:
            content += f"Labels: {', '.join(labels)}\n"
        content += f"URL: {url}"

        try:
            from decisionssearch.domain.memory.raw_event import RawEvent
            import uuid

            event = RawEvent(
                event_id=str(uuid.uuid4()),
                source_kind="shortcut_card",
                payload=content,
                project_hint=self._project,
                metadata={"story_id": story_id, "story_type": story_type},
            )
            self.container.landing_zone.append_raw_event(event)

            candidates = await self.container.extraction.extract_candidates(
                content=content,
                project=self._project,
                probable_category="ProjectKnowledge",
                domain=labels,
            )
            for candidate in candidates:
                admission_result = await self.container.admission.evaluate(candidate)
                if admission_result.status in ("active", "proposed"):
                    await self.container.persistence.persist(candidate, admission_result)
                    return True
        except Exception as e:
            logger.warning("Failed to ingest Shortcut card #%s: %s", story_id, e)
        return False
