from decisionssearch.application.catalog.graph_clustering_service import GraphClusteringService


def test_group_by_connectivity_empty():
    svc = GraphClusteringService(neo4j=None)
    result = svc._group_by_connectivity([])
    assert result == []


def test_group_by_connectivity_groups():
    svc = GraphClusteringService(neo4j=None)
    records = [
        {"memory_id": "m1", "title": "Rule 1", "weight": 0.9},
        {"memory_id": "m2", "title": "Rule 2", "weight": 0.5},
        {"memory_id": "m3", "title": "Rule 3", "weight": 0.7},
    ]
    result = svc._group_by_connectivity(records)
    assert len(result) == 3
    assert result[0]["community_id"] == "comm-1"


def test_group_deduplicates():
    svc = GraphClusteringService(neo4j=None)
    records = [
        {"memory_id": "m1", "title": "A", "weight": 0.5},
        {"memory_id": "m1", "title": "A", "weight": 0.5},
    ]
    result = svc._group_by_connectivity(records)
    assert len(result) == 1
