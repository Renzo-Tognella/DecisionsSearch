from decisionssearch.application.search.cross_memory_synthesis_service import CrossMemorySynthesisService


def test_cluster_by_title_similarity():
    svc = CrossMemorySynthesisService(neo4j=None)
    memories = [
        {"memory_id": "m1", "title": "use guard clauses for validation"},
        {"memory_id": "m2", "title": "use guard clause for validations"},
        {"memory_id": "m3", "title": "always log errors with context"},
        {"memory_id": "m4", "title": "always log error with contexts"},
    ]
    clusters = svc._cluster_by_title_similarity(memories)
    assert len(clusters) == 2
    sizes = sorted([len(c) for c in clusters])
    assert sizes == [2, 2]


def test_cluster_single_memory():
    svc = CrossMemorySynthesisService(neo4j=None)
    memories = [{"memory_id": "m1", "title": "unique rule"}]
    clusters = svc._cluster_by_title_similarity(memories)
    assert len(clusters) == 1
    assert len(clusters[0]) == 1


def test_cluster_no_similar():
    svc = CrossMemorySynthesisService(neo4j=None)
    memories = [
        {"memory_id": "m1", "title": "authentication pattern"},
        {"memory_id": "m2", "title": "database migration rule"},
        {"memory_id": "m3", "title": "error handling convention"},
    ]
    clusters = svc._cluster_by_title_similarity(memories)
    assert len(clusters) == 3
    assert all(len(c) == 1 for c in clusters)


def test_synthesize_cluster():
    svc = CrossMemorySynthesisService(neo4j=None)
    import asyncio

    cluster = {
        "cluster_id": "abc123",
        "size": 3,
        "titles": ["rule1", "rule2", "rule3"],
        "memory_ids": ["m1", "m2", "m3"],
    }
    result = asyncio.run(svc.synthesize_cluster(cluster, project="CORE"))
    assert result["cluster_id"] == "abc123"
    assert result["synthesis"] is not None
