import os

from decisionssearch.infrastructure.config.env_utils import env_bool, env_int
from decisionssearch.infrastructure.ai.providers.model_provider import get_embedding_dimensions

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    def load_dotenv() -> bool:
        return False

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        SparseIndexParams,
        SparseVectorParams,
        VectorParams,
    )
except Exception:  # pragma: no cover
    class QdrantClient:  # type: ignore[override]
        def __init__(self, *args, **kwargs):  # noqa: ANN002,ANN003
            raise RuntimeError("qdrant_client indisponível no ambiente atual")

    class _DistanceValue:
        def __init__(self, value: str):
            self.value = value

    class Distance:  # type: ignore[override]
        COSINE = _DistanceValue("Cosine")

    class VectorParams:  # type: ignore[override]
        def __init__(self, size: int, distance):
            self.size = size
            self.distance = distance

    class SparseIndexParams:  # type: ignore[override]
        def __init__(self, on_disk: bool = False):
            self.on_disk = on_disk

    class SparseVectorParams:  # type: ignore[override]
        def __init__(self, index=None):
            self.index = index


def get_settings() -> dict[str, str | int]:
    load_dotenv()
    return {
        "host": os.getenv("QDRANT_HOST", "localhost"),
        "port": env_int("QDRANT_PORT", 6333),
        "collection_name": os.getenv("QDRANT_COLLECTION", "memories"),
        "dimensions": get_embedding_dimensions(),
    }


def build_client(host: str, port: int) -> QdrantClient:
    return QdrantClient(host=host, port=port)


def ensure_collection(
    client: QdrantClient,
    collection_name: str,
    dimensions: int,
    sparse_enabled: bool | None = None,
) -> bool:
    enabled = env_bool("SPARSE_SEARCH_ENABLED", False) if sparse_enabled is None else sparse_enabled
    if client.collection_exists(collection_name):
        if enabled:
            info = client.get_collection(collection_name)
            params = getattr(getattr(info, "config", None), "params", None)
            sparse_vectors = getattr(params, "sparse_vectors", None)
            sparse_names = set(sparse_vectors.keys()) if hasattr(sparse_vectors, "keys") else set()
            vector_name = os.getenv("SPARSE_VECTOR_NAME", "bm25").strip() or "bm25"
            if vector_name not in sparse_names:
                raise RuntimeError(
                    f"Collection '{collection_name}' não tem o vetor sparse '{vector_name}'. "
                    "Crie uma collection nova com SPARSE_SEARCH_ENABLED=true, reindexe "
                    "as memórias e aponte QDRANT_COLLECTION para ela após validar."
                )
        return False

    create_kwargs = {
        "collection_name": collection_name,
        "vectors_config": VectorParams(size=dimensions, distance=Distance.COSINE),
    }
    if enabled:
        vector_name = os.getenv("SPARSE_VECTOR_NAME", "bm25").strip() or "bm25"
        create_kwargs["sparse_vectors_config"] = {
            vector_name: SparseVectorParams(
                index=SparseIndexParams(on_disk=env_bool("SPARSE_INDEX_ON_DISK", False))
            )
        }
    client.create_collection(**create_kwargs)
    return True


def main() -> None:
    settings = get_settings()
    client = build_client(
        host=settings["host"],
        port=settings["port"],
    )
    created = ensure_collection(
        client=client,
        collection_name=settings["collection_name"],
        dimensions=settings["dimensions"],
    )

    if created:
        print(f"Collection '{settings['collection_name']}' criada com sucesso.")
        return

    print(f"Collection '{settings['collection_name']}' ja existe.")


if __name__ == "__main__":
    main()
