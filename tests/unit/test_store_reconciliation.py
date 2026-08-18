import asyncio
from unittest.mock import AsyncMock, MagicMock

from decisionssearch.application.memory.consolidation_service import ConsolidationService


def _make_service(neo4j_ids=None, qdrant_ids=None):
    neo4j = MagicMock()
    rows = []
    for mid in neo4j_ids or []:
        rows.append({"memory": {"memory_id": mid}})
    neo4j.query_by_project = AsyncMock(return_value=rows)
    neo4j.list_projects = AsyncMock(return_value=["CORE"])
    neo4j.deprecate_memory = AsyncMock()
    qdrant = MagicMock()
    qdrant.get_all_memory_ids = AsyncMock(return_value=qdrant_ids or [])
    qdrant.delete = AsyncMock()
    qdrant.update_payload = AsyncMock()
    return ConsolidationService(neo4j=neo4j, qdrant=qdrant)


def test_reconcile_no_divergence():
    svc = _make_service(neo4j_ids=["m1"], qdrant_ids=["m1"])
    result = asyncio.run(svc.reconcile_stores())
    assert result["neo4j_orphans"] == 0
    assert result["qdrant_orphans"] == 0


def test_reconcile_detects_qdrant_orphans():
    svc = _make_service(neo4j_ids=["m1"], qdrant_ids=["m1", "orphan-1"])
    result = asyncio.run(svc.reconcile_stores())
    assert result["qdrant_orphans"] == 1


def test_reconcile_deletes_qdrant_orphans():
    svc = _make_service(neo4j_ids=["m1"], qdrant_ids=["m1", "orphan-1"])
    result = asyncio.run(svc.reconcile_stores())
    svc.qdrant.delete.assert_called_once_with("orphan-1")
    assert result["cleaned"] == 1


def test_reconcile_detects_neo4j_orphans():
    svc = _make_service(neo4j_ids=["m1", "no-vector"], qdrant_ids=["m1"])
    result = asyncio.run(svc.reconcile_stores())
    assert result["neo4j_orphans"] == 1


def test_reconcile_returns_counts():
    svc = _make_service(neo4j_ids=["m1", "m2"], qdrant_ids=["m1", "orphan"])
    result = asyncio.run(svc.reconcile_stores())
    assert result["neo4j_count"] == 2
    assert result["qdrant_count"] == 2
