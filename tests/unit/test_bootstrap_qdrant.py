from scripts.bootstrap_qdrant import ensure_collection, get_settings


class StubQdrantClient:
    def __init__(self, exists: bool) -> None:
        self.exists = exists
        self.created_collection_name: str | None = None
        self.created_vector_size: int | None = None
        self.created_distance: str | None = None

    def collection_exists(self, collection_name: str) -> bool:
        return self.exists and collection_name == "memories"

    def create_collection(self, collection_name, vectors_config, sparse_vectors_config=None) -> None:
        self.created_collection_name = collection_name
        self.created_vector_size = vectors_config.size
        self.created_distance = vectors_config.distance.value
        self.created_sparse_vectors = sparse_vectors_config


def test_get_settings_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv("QDRANT_HOST", "qdrant.local")
    monkeypatch.setenv("QDRANT_PORT", "7000")
    monkeypatch.setenv("QDRANT_COLLECTION", "knowledge")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "1536")

    assert get_settings() == {
        "host": "qdrant.local",
        "port": 7000,
        "collection_name": "knowledge",
        "dimensions": 1536,
    }


def test_ensure_collection_creates_missing_collection() -> None:
    client = StubQdrantClient(exists=False)

    created = ensure_collection(client, "memories", 512)

    assert created is True
    assert client.created_collection_name == "memories"
    assert client.created_vector_size == 512
    assert client.created_distance == "Cosine"


def test_ensure_collection_skips_existing_collection() -> None:
    client = StubQdrantClient(exists=True)

    created = ensure_collection(client, "memories", 512, sparse_enabled=False)

    assert created is False
    assert client.created_collection_name is None


def test_ensure_collection_can_create_sparse_vector() -> None:
    client = StubQdrantClient(exists=False)

    created = ensure_collection(client, "memories", 512, sparse_enabled=True)

    assert created is True
    assert "bm25" in client.created_sparse_vectors


def test_ensure_collection_rejects_sparse_on_old_dense_collection() -> None:
    class DenseOnlyClient:
        def collection_exists(self, collection_name: str) -> bool:
            return True

        def get_collection(self, collection_name: str):
            from types import SimpleNamespace

            return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(sparse_vectors={})))

    try:
        ensure_collection(DenseOnlyClient(), "memories", 512, sparse_enabled=True)
    except RuntimeError as error:
        assert "SPARSE_SEARCH_ENABLED=true" in str(error)
        assert "collection nova" in str(error)
    else:
        raise AssertionError("esperava erro de schema sparse ausente")
