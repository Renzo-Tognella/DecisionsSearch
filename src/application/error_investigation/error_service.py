from __future__ import annotations

from typing import Any

from decisionssearch.domain.incidents.error_event import ErrorEvent
from decisionssearch.domain.incidents.investigation import Investigation
from decisionssearch.domain.memory_ledger import MemoryScope
from decisionssearch.application.memory.ledger.adapters import hydrate_legacy


class ErrorService:
    def __init__(self, neo4j: Any = None, ledger=None):  # noqa: ANN001
        self.neo4j = neo4j
        self.ledger = ledger

    async def ingest_error(self, event: ErrorEvent) -> ErrorEvent:
        if not self.neo4j:
            return event

        query = """
        MERGE (e:Error {stack_trace_hash: $hash, service: $service, environment: $env})
        ON CREATE SET
            e.error_id = $error_id,
            e.timestamp = datetime($timestamp),
            e.error_type = $error_type,
            e.error_message = $message,
            e.stack_trace = $trace,
            e.severity = $severity,
            e.status = 'open',
            e.count = 1,
            e.first_seen = datetime($timestamp),
            e.last_seen = datetime($timestamp),
            e.host = $host,
            e.request_id = $request_id,
            e.fingerprint = $fingerprint
        ON MATCH SET
            e.count = e.count + 1,
            e.last_seen = datetime($timestamp),
            e.status = CASE WHEN e.status = 'resolved' THEN 'open' ELSE e.status END
        RETURN e.count AS count,
               CASE WHEN e.count = 1 THEN 'new' ELSE 'duplicate' END AS outcome
        """
        result = await self.neo4j.execute_write(query,
            hash=event.stack_trace_hash,
            service=event.service,
            env=event.environment,
            error_id=event.error_id,
            timestamp=event.timestamp,
            error_type=event.error_type,
            message=event.error_message[:1000],
            trace=event.stack_trace[:5000],
            severity=event.severity.value,
            host=event.host,
            request_id=event.request_id,
            fingerprint=event.fingerprint or event.stack_trace_hash,
        )
        if result:
            event.count = result[0].get("count", 1)
        return event

    async def find_suspect_prs(self, error_id: str) -> list[dict]:
        if not self.neo4j:
            return []

        if self.ledger is not None:
            error_rows = await self.neo4j.execute_read(
                "MATCH (e:Error {error_id: $error_id}) RETURN e.timestamp AS timestamp",
                error_id=error_id,
            )
            file_rows = await self.neo4j.execute_read(
                "MATCH (e:Error {error_id: $error_id})-[:OCCURRED_IN]->(f:File) RETURN f.path AS path",
                error_id=error_id,
            )
            if not error_rows:
                return []
            error_timestamp = error_rows[0].get("timestamp")
            paths = {str(row.get("path", "")) for row in file_rows}
            revisions = await self.ledger.list_effective_revisions(memory_scope=MemoryScope.PULL_REQUEST)
            suspects = []
            for revision in revisions:
                row = hydrate_legacy(revision)
                changed_files = set(row.get("changed_files", []))
                if paths and not any(path in changed_files for path in paths):
                    continue
                merged_at = str(row.get("merged_at", ""))
                if error_timestamp and merged_at and merged_at >= str(error_timestamp):
                    continue
                suspects.append(
                    {
                        "file_path": next(iter(paths), ""),
                        "pr_number": row.get("pr_number"),
                        "pr_title": row.get("title"),
                        "pr_authors": row.get("authors", []),
                        "repo": row.get("repo"),
                        "pr_url": row.get("pr_url"),
                        "memory_id": dict(revision.content.legacy_ids).get("memory_id"),
                        "revision_id": str(revision.revision_id),
                    }
                )
            return suspects[:10]

        query = """
        MATCH (error:Error {error_id: $error_id})
        MATCH (error)-[:OCCURRED_IN]->(file:File)
        MATCH (pr:PRMemory)-[:MODIFIED]->(file)
        WHERE pr.merged_at < error.timestamp
        RETURN file.path AS file_path, pr.pr_number AS pr_number,
               pr.title AS pr_title, pr.authors AS pr_authors,
               pr.repo AS repo, pr.pr_url AS pr_url
        ORDER BY pr.merged_at DESC LIMIT 10
        """
        return await self.neo4j.execute_read(query, error_id=error_id) or []

    async def list_errors(
        self, service: str = "", status: str = "", error_type: str = "", limit: int = 50,
    ) -> list[dict]:
        if not self.neo4j:
            return []

        query = "MATCH (e:Error) WHERE 1=1 "
        params: dict[str, Any] = {}
        if service:
            query += "AND e.service = $service "
            params["service"] = service
        if status:
            query += "AND e.status = $status "
            params["status"] = status
        if error_type:
            query += "AND e.error_type = $error_type "
            params["error_type"] = error_type
        query += "RETURN e ORDER BY e.last_seen DESC LIMIT $limit"
        params["limit"] = limit

        return await self.neo4j.execute_read(query, **params) or []

    async def get_error(self, error_id: str) -> dict | None:
        if not self.neo4j:
            return None
        results = await self.neo4j.execute_read(
            "MATCH (e:Error {error_id: $id}) RETURN e", id=error_id,
        )
        return results[0] if results else None

    async def link_files(self, error_id: str, files: list[dict]) -> None:
        if not self.neo4j:
            return
        for f in files:
            await self.neo4j.execute_write("""
                MATCH (e:Error {error_id: $error_id})
                MERGE (f:File {path: $path, repo: $repo})
                ON CREATE SET f.name = $name
                MERGE (e)-[:OCCURRED_IN {line: $line, frame_index: $idx}]->(f)
            """,
                error_id=error_id,
                path=f["path"], repo=f.get("repo", ""),
                name=f.get("name", ""), line=f.get("line", 0),
                idx=f.get("idx", 0),
            )

    async def create_investigation(self, inv: Investigation) -> Investigation:
        if not self.neo4j:
            return inv
        await self.neo4j.execute_write("""
            MATCH (e:Error {error_id: $error_id})
            CREATE (inv:Investigation {
                investigation_id: $inv_id,
                started_at: datetime($started_at),
                status: $status,
                investigator: $investigator,
                hypothesis: $hypothesis
            })
            CREATE (inv)-[:INVESTIGATES]->(e)
            SET e.status = 'investigating'
        """,
            error_id=inv.error_id,
            inv_id=inv.investigation_id,
            started_at=inv.started_at,
            status=inv.status.value,
            investigator=inv.investigator,
            hypothesis=inv.hypothesis,
        )
        return inv

    async def complete_investigation(
        self, inv_id: str, findings: str, fix_pr_url: str = "",
    ) -> None:
        if not self.neo4j:
            return
        await self.neo4j.execute_write("""
            MATCH (inv:Investigation {investigation_id: $inv_id})
            SET inv.status = 'completed',
                inv.completed_at = datetime(),
                inv.findings = $findings,
                inv.fix_pr_url = $fix_url
            WITH inv
            MATCH (inv)-[:INVESTIGATES]->(e:Error)
            SET e.status = CASE WHEN $fix_url <> '' THEN 'resolved' ELSE 'investigating' END
        """, inv_id=inv_id, findings=findings, fix_url=fix_pr_url)

    async def get_investigation(self, error_id: str) -> dict | None:
        if not self.neo4j:
            return None
        results = await self.neo4j.execute_read("""
            MATCH (inv:Investigation)-[:INVESTIGATES]->(e:Error {error_id: $error_id})
            RETURN inv ORDER BY inv.started_at DESC LIMIT 1
        """, error_id=error_id)
        return results[0] if results else None
