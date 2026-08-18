import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "src"


def _python_source(root: Path) -> str:
    return "\n".join(path.read_text() for path in root.rglob("*.py"))


def test_new_package_does_not_import_legacy_packages() -> None:
    source = _python_source(PACKAGE_ROOT)

    assert not re.search(r"\b(?:from|import) (?:models|services|server)(?:\.|\s|$)", source)


def test_domain_does_not_depend_on_application_or_adapters() -> None:
    source = _python_source(PACKAGE_ROOT / "domain")

    assert "decisionssearch.application" not in source
    assert "decisionssearch.infrastructure" not in source
    assert "decisionssearch.interfaces" not in source
