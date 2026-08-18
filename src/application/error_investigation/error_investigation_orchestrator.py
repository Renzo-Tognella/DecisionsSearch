from __future__ import annotations

import logging
import re
from typing import Any

from decisionssearch.domain.incidents.error_event import ErrorEvent
from decisionssearch.domain.incidents.investigation import Investigation, InvestigationResult
from decisionssearch.infrastructure.agents.agent_worker import AgentWorker, AgentResult
from decisionssearch.infrastructure.integrations.github_service import GitHubService

logger = logging.getLogger(__name__)

ERROR_INVESTIGATION_PROMPT = """\
## TASK: Investigate and fix the following error

### ERROR DETAILS
- **Error Type:** {error_type}
- **Error Message:** {error_message}
- **Stack Trace:**
```
{stack_trace}
```
- **Service:** {service}
- **Environment:** {environment}

### SUSPECT PRs (from DecisionsSearch memory)
{suspect_prs}

### CONSTRAINTS
- Do NOT modify tests unless the test itself is wrong
- Follow existing code conventions
- Prefer minimal fixes over refactors

### EXPECTED OUTPUT (JSON block)
```json
{{
  "status": "fixed" | "needs_human" | "unclear",
  "root_cause": "...",
  "fix_description": "...",
  "files_modified": ["path/to/file.py"],
  "confidence": 0.0-1.0,
  "suspect_pr_identified": "pr_memory_id or null",
  "risks": ["..."],
  "testing_notes": "..."
}}
```
"""


class ErrorInvestigationOrchestrator:
    def __init__(
        self,
        error_service: Any = None,
        pr_memory: Any = None,
        notification_service: Any = None,
        worker: AgentWorker | None = None,
        github: GitHubService | None = None,
        safety: dict | None = None,
    ):
        self.error_service = error_service
        self.pr_memory = pr_memory
        self.notification = notification_service
        self.worker = worker
        self.github = github
        self.safety = safety or {}
        self._fix_timestamps: list[float] = []

    async def handle_error(self, event: ErrorEvent, repo_url: str = "", base_branch: str = "main") -> dict:
        error_id = event.error_id
        logger.info("Handling error %s: %s", error_id, event.error_type)

        if self.error_service:
            event = await self.error_service.ingest_error(event)

        if self.error_service and event.stack_frames:
            files = [
                {
                    "path": sf.file,
                    "line": sf.line,
                    "name": sf.file.rsplit("/", 1)[-1] if "/" in sf.file else sf.file,
                    "idx": i,
                }
                for i, sf in enumerate(event.stack_frames)
            ]
            await self.error_service.link_files(error_id, files)

        suspect_prs = []
        if self.error_service:
            suspect_prs = await self.error_service.find_suspect_prs(error_id)

        if not suspect_prs:
            logger.info("No suspect PRs found for error %s", error_id)
            if self.notification:
                await self.notification.notify_investigation(
                    title=f"Error: {event.error_type} (no suspects)",
                    body=f"No suspect PRs found for error in `{event.service}`.\n\n"
                         f"**Error:** {event.error_type}: {event.error_message[:500]}\n"
                         f"**Stack trace parsed files:** {[sf.file for sf in event.stack_frames[:5]]}",
                    metadata={"error_id": error_id, "service": event.service},
                )
            return {"status": "skipped", "reason": "no_suspect_prs"}

        if not self._check_circuit_breaker():
            logger.warning("Circuit breaker open — too many auto-fixes")
            if self.notification:
                await self.notification.notify_investigation(
                    title=f"Circuit breaker: {event.error_type}",
                    body=f"Circuit breaker open — auto-fix blocked for `{event.error_type}` in `{event.service}`.\n"
                         f"Error: {event.error_message[:500]}",
                    metadata={"error_id": error_id, "service": event.service, "suspect_prs": [p.get("pr_number") for p in suspect_prs[:5]]},
                )
            return {"status": "skipped", "reason": "circuit_breaker_open"}

        prompt = self._build_prompt(event, suspect_prs)
        if not self.worker:
            if self.notification:
                await self.notification.notify_investigation(
                    title=f"Error: {event.error_type} (no worker)",
                    body=f"No agent worker configured — cannot investigate `{event.error_type}` in `{event.service}`.",
                    metadata={"error_id": error_id, "service": event.service},
                )
            return {"status": "skipped", "reason": "no_agent_worker"}

        result: AgentResult = await self.worker.run(prompt)

        investigation_result = InvestigationResult(**result.extracted) if result.extracted else InvestigationResult(
            status="unclear", root_cause=result.error or "Failed to parse output",
        )
        investigation_result.files_modified = result.extracted.get("files_modified", [])
        investigation_result.confidence = result.extracted.get("confidence", 0.0)

        inv = Investigation(
            error_id=error_id,
            findings=investigation_result.root_cause,
            confidence=investigation_result.confidence,
        )
        if self.error_service:
            await self.error_service.create_investigation(inv)

        if self._is_blocked_path(investigation_result.files_modified):
            logger.warning("Agent tried to modify blocked paths — notifying instead of auto-fixing")
            investigation_result.status = "needs_human"

        min_conf = self.safety.get("min_confidence", 0.7)
        if investigation_result.status == "fixed" and investigation_result.confidence >= min_conf:
            return await self._auto_fix(event, investigation_result, inv, base_branch)

        if self.notification:
            await self.notification.notify_investigation(
                title=f"Investigation: {event.error_type}",
                body=f"Root cause: {investigation_result.root_cause}\nConfidence: {investigation_result.confidence}",
                metadata={"error_id": error_id, "suspect_prs": suspect_prs},
            )

        return {
            "status": investigation_result.status,
            "root_cause": investigation_result.root_cause,
        }

    def _check_circuit_breaker(self) -> bool:
        import time
        now = time.time()
        max_per_hour = self.safety.get("max_auto_fixes_per_hour", 3)
        self._fix_timestamps = [t for t in self._fix_timestamps if now - t < 3600]
        return len(self._fix_timestamps) < max_per_hour

    def _is_blocked_path(self, files: list[str]) -> bool:
        blocked = self.safety.get("blocked_paths", [])
        for f in files:
            for bp in blocked:
                if bp.rstrip("/") in f:
                    return True
        return False

    async def _auto_fix(
        self, event: ErrorEvent, result: InvestigationResult,
        inv: Investigation, base_branch: str,
    ) -> dict:
        import time
        self._fix_timestamps.append(time.time())

        if not self.github:
            return {"status": "no_github_service"}

        fix_slug = re.sub(r"[^a-z0-9]+", "-", result.root_cause.lower()).strip("-")[:50]
        author = ""
        if hasattr(self, "pr_memory") and self.pr_memory and result.suspect_pr_identified:
            pr = await self.pr_memory.get_pr_memory(result.suspect_pr_identified)
            if pr:
                authors = pr.get("authors", [])
                author = f"@{authors[0]}" if authors else ""

        pr_body = f"""## Auto-fix for error

**Error:** {event.error_type}: {event.error_message}
**Root cause:** {result.root_cause}
**Fix:** {result.fix_description}
**Files modified:** {", ".join(result.files_modified)}
**Confidence:** {result.confidence}

{result.testing_notes}
"""
        pr_result = await self.github.create_pr(
            title=f"fix: {result.root_cause[:80]}",
            body=pr_body,
            base_branch=base_branch,
            head_branch=f"fix/{fix_slug}",
            reviewer=author,
            labels=self.safety.get("pr_labels", ["auto-fix", "needs-review"]),
        )

        if self.error_service and pr_result.get("pr_url"):
            await self.error_service.complete_investigation(
                inv.investigation_id, result.root_cause, pr_result["pr_url"],
            )

        if self.notification:
            await self.notification.notify_investigation(
                title=f"Auto-fix PR for {event.error_type}",
                body=f"PR: {pr_result.get('pr_url', 'N/A')}\n{result.root_cause}",
                url=pr_result.get("pr_url", ""),
                metadata={"pr_result": pr_result},
            )

        return pr_result

    def _build_prompt(self, event: ErrorEvent, suspect_prs: list[dict]) -> str:
        pr_lines = []
        for pr in suspect_prs[:5]:
            pr_lines.append(f"- PR #{pr.get('pr_number', '?')}: {pr.get('pr_title', '')} "
                           f"(repo: {pr.get('repo', '')}, authors: {pr.get('authors', [])})")
        return ERROR_INVESTIGATION_PROMPT.format(
            error_type=event.error_type,
            error_message=event.error_message,
            stack_trace=event.stack_trace or "N/A",
            service=event.service,
            environment=event.environment,
            suspect_prs="\n".join(pr_lines) if pr_lines else "None found",
        )
