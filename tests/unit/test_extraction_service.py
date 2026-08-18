import instructor

from decisionssearch.application.memory.extraction_service import ExtractionService


def test_openrouter_structured_extraction_uses_json_transport(monkeypatch):
    service = ExtractionService.__new__(ExtractionService)
    service.provider = "openrouter"
    service.client = object()
    captured = {}

    def fake_from_openai(client, **kwargs):
        captured["client"] = client
        captured.update(kwargs)
        return "structured-client"

    monkeypatch.setattr(instructor, "from_openai", fake_from_openai)

    assert service._build_structured_client() == "structured-client"
    assert captured["client"] is service.client
    assert captured["mode"] == instructor.Mode.JSON
