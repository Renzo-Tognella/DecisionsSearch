import asyncio
import threading
import time

from decisionssearch.infrastructure.ai.embeddings.embedding_providers import LocalMiniLMEmbeddingProvider


class _Vector:
    def tolist(self):
        return [0.1, 0.2]


class _ThreadSensitiveModel:
    def __init__(self):
        self._state_lock = threading.Lock()
        self.active_calls = 0
        self.max_active_calls = 0

    def encode(self, text, **kwargs):
        del text, kwargs
        with self._state_lock:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        time.sleep(0.01)
        with self._state_lock:
            self.active_calls -= 1
        return _Vector()


def test_local_embedding_serializes_shared_model_access():
    provider = LocalMiniLMEmbeddingProvider.__new__(LocalMiniLMEmbeddingProvider)
    provider.model_name = "test-model"
    provider.dimensions = 2
    provider.model = _ThreadSensitiveModel()
    provider._encode_lock = threading.Lock()

    async def run_concurrently():
        return await asyncio.gather(provider.embed("one"), provider.embed("two"))

    vectors = asyncio.run(run_concurrently())

    assert vectors == [[0.1, 0.2], [0.1, 0.2]]
    assert provider.model.max_active_calls == 1
