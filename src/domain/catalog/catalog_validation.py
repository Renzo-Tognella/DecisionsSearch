from __future__ import annotations

import hashlib
import re

SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")


def normalize_required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def normalize_optional_text(value: object, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value.strip()


def normalize_slug(value: object) -> str:
    slug = normalize_required_text(value, "slug").lower()
    if not SLUG_PATTERN.fullmatch(slug):
        raise ValueError("slug must contain only lowercase letters, numbers and '-'")
    return slug


def normalize_unique_aliases(value: object) -> list[str]:
    return _normalize_string_list(value, case_insensitive=False)


def normalize_semantic_strings(value: object) -> list[str]:
    return _normalize_string_list(value, case_insensitive=True)


def generate_catalog_id(kind: str, slug: str, scope: str | None = None) -> str:
    normalized_kind = normalize_required_text(kind, "kind").lower()
    normalized_slug = normalize_slug(slug)
    normalized_scope = normalize_optional_text(scope, "scope").lower() if scope is not None else ""
    seed = f"{normalized_kind}:{normalized_scope}:{normalized_slug}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _normalize_string_list(value: object, *, case_insensitive: bool) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    else:
        try:
            items = list(value)
        except TypeError as error:
            raise ValueError("value must be an iterable of strings") from error

    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            raise ValueError("list items must be strings")
        stripped = item.strip()
        if not stripped:
            continue
        key = stripped.casefold() if case_insensitive else stripped
        if key in seen:
            continue
        seen.add(key)
        normalized.append(stripped)
    return normalized
