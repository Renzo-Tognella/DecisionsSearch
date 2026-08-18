import pytest

from decisionssearch.domain.shared.exceptions import SanitizationError
from decisionssearch.application.memory.sanitization_service import SanitizationService


def test_sanitize_removes_cpf_and_password() -> None:
    service = SanitizationService()
    result = service.sanitize("CPF: 123.456.789-00 senha: abc123")
    assert "[CPF_REMOVIDO]" in result
    assert "[CREDENCIAL_REMOVIDA]" in result


def test_has_sensitive_content_detects_email() -> None:
    service = SanitizationService()
    assert service.has_sensitive_content("email: user@example.com")


def test_validate_payload_size_raises() -> None:
    service = SanitizationService()
    payload = "x" * 50_001
    with pytest.raises(SanitizationError):
        service.validate_payload_size(payload)
