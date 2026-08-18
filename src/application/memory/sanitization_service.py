from __future__ import annotations

import re

from decisionssearch.domain.shared.exceptions import SanitizationError

MAX_PAYLOAD_SIZE = 50_000


class SanitizationService:
    """Remove PII/credenciais e valida tamanho de payload."""

    PII_PATTERNS: list[tuple[str, str]] = [
        (r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", "[CPF_REMOVIDO]"),
        (r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", "[CNPJ_REMOVIDO]"),
        (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[EMAIL_REMOVIDO]"),
        (r"(?i)(senha|password|token|api.?key|secret)\s*[:=]\s*\S+", "[CREDENCIAL_REMOVIDA]"),
        (r"sk-[a-zA-Z0-9]{20,}", "[API_KEY_REMOVIDA]"),
        (r"ghp_[a-zA-Z0-9]{36}", "[GITHUB_TOKEN_REMOVIDO]"),
        (r"\bAKIA[0-9A-Z]{16}\b", "[AWS_KEY_REMOVIDA]"),
        (r"eyJ[A-Za-z0-9-_]+\.eyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+", "[JWT_REMOVIDO]"),
        (r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*", "[BEARER_TOKEN_REMOVIDO]"),
    ]

    def sanitize(self, text: str) -> str:
        result = text
        for pattern, replacement in self.PII_PATTERNS:
            result = re.sub(pattern, replacement, result)
        return result

    def has_sensitive_content(self, text: str) -> bool:
        return any(re.search(pattern, text) for pattern, _ in self.PII_PATTERNS)

    def validate_payload_size(self, payload: str) -> None:
        size = len(payload.encode("utf-8"))
        if size > MAX_PAYLOAD_SIZE:
            raise SanitizationError(
                f"Payload excede {MAX_PAYLOAD_SIZE} bytes",
                reason="payload_too_large",
                context={"payload_bytes": size},
            )

    def sanitize_output(self, data: dict) -> dict:
        sanitized = {}
        for key, value in data.items():
            if isinstance(value, str):
                sanitized[key] = self.sanitize(value)
            elif isinstance(value, dict):
                sanitized[key] = self.sanitize_output(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    self.sanitize_output(item)
                    if isinstance(item, dict)
                    else self.sanitize(item)
                    if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                sanitized[key] = value
        return sanitized
