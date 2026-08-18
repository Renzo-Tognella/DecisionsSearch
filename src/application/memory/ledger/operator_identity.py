"""Resolução da identidade que pode aprovar alterações do ledger.

Em produção, a identidade deve vir de um gateway/IdP ou de credenciais
configuradas fora do agente. O fallback por ``X-Operator-Id`` existe apenas
para desenvolvimento local e fica explicitamente marcado como tal.
"""

from __future__ import annotations

import hmac
import os

from decisionssearch.domain.shared.exceptions import ApprovalError


class TrustedOperatorResolver:
    """Resolve um principal a partir de credencial configurada.

    ``DECISIONSSEARCH_OPERATOR_TOKENS`` aceita entradas separadas por vírgula no
    formato ``token=operator_id``. O token nunca é retornado nem registrado.
    Quando a variável não está configurada, o modo local aceita o principal
    declarado para manter o fluxo de desenvolvimento, mas não o considera
    autenticação forte.
    """

    def __init__(self, credentials: dict[str, str] | None = None) -> None:
        self.credentials = credentials or {}

    @classmethod
    def from_env(cls) -> "TrustedOperatorResolver":
        raw = os.getenv("DECISIONSSEARCH_OPERATOR_TOKENS", "")
        credentials: dict[str, str] = {}
        for entry in raw.split(","):
            if "=" not in entry:
                continue
            token, principal = (part.strip() for part in entry.split("=", 1))
            if token and principal:
                credentials[token] = principal
        return cls(credentials)

    def resolve(self, claimed_principal: str | None, credential: str | None = None) -> str:
        if not self.credentials:
            if os.getenv("DECISIONSSEARCH_ALLOW_INSECURE_LOCAL_OPERATOR", "false").casefold() not in {
                "1",
                "true",
                "yes",
            }:
                raise ApprovalError(
                    "Nenhuma credencial de operador configurada; habilite apenas o modo local explicitamente"
                )
            if not claimed_principal:
                raise ApprovalError("Operador não identificado")
            return claimed_principal
        if not credential:
            raise ApprovalError("Credencial de operador obrigatória")
        principal = next(
            (
                value
                for token, value in self.credentials.items()
                if hmac.compare_digest(token, credential)
            ),
            None,
        )
        if principal is None:
            raise ApprovalError("Credencial de operador inválida")
        if claimed_principal and not hmac.compare_digest(principal, claimed_principal):
            raise ApprovalError("A identidade declarada não corresponde à credencial")
        return principal
