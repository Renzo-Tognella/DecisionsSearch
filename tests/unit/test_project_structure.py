from importlib import import_module
from pathlib import Path
import tomllib

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"


def test_expected_directories_exist() -> None:
    expected_directories = [
        "src",
        "src/domain",
        "src/application",
        "src/infrastructure",
        "src/interfaces",
        "src/bootstrap",
        "scripts",
        "tests",
    ]

    for directory in expected_directories:
        assert (PROJECT_ROOT / directory).is_dir()

    assert not (SOURCE_ROOT / "decisionssearch").exists()


def test_expected_configuration_files_exist() -> None:
    expected_files = [
        ".env.example",
        "README.md",
        "pyproject.toml",
        "src/interfaces/mcp/main.py",
        "src/interfaces/mcp/prompts.py",
        "src/interfaces/mcp/resources.py",
        "src/interfaces/mcp/tools.py",
        "src/application/memory/admission_service.py",
        "src/infrastructure/ai/embeddings/embedding_service.py",
        "src/application/memory/extraction_service.py",
        "src/infrastructure/persistence/neo4j/neo4j_service.py",
        "src/infrastructure/persistence/qdrant/qdrant_service.py",
        "src/infrastructure/ai/embeddings/sparse_embedding_service.py",
        "src/application/memory/commit_memory_hook.py",
        "src/bootstrap/container.py",
        ".githooks/post-commit",
        "scripts/post_commit_memory_hook.py",
        "scripts/install_git_hooks.py",
    ]

    for file_path in expected_files:
        assert (PROJECT_ROOT / file_path).is_file()


@pytest.mark.parametrize(
    "module_name",
    [
        "decisionssearch.domain",
        "decisionssearch.domain.memory.memory_candidate",
        "decisionssearch.domain.memory.memory_item",
        "decisionssearch.domain.memory.raw_event",
        "decisionssearch.application",
        "decisionssearch.infrastructure",
        "decisionssearch.interfaces",
        "decisionssearch.bootstrap",
        "decisionssearch.interfaces.mcp.main",
    ],
)
def test_modules_import(module_name: str) -> None:
    import_module(module_name)


def test_domain_does_not_depend_on_outer_layers() -> None:
    domain_root = SOURCE_ROOT / "domain"
    source = "\n".join(path.read_text() for path in domain_root.rglob("*.py"))

    assert "decisionssearch.application" not in source
    assert "decisionssearch.infrastructure" not in source
    assert "decisionssearch.interfaces" not in source


def test_declared_packages_match_source_tree() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    setuptools_config = pyproject["tool"]["setuptools"]

    assert setuptools_config["package-dir"] == {"decisionssearch": "src"}

    discovered_packages = set()
    for init_file in SOURCE_ROOT.rglob("__init__.py"):
        relative_package = init_file.parent.relative_to(SOURCE_ROOT)
        suffix = ".".join(relative_package.parts)
        discovered_packages.add("decisionssearch" + (f".{suffix}" if suffix else ""))

    assert set(setuptools_config["packages"]) == discovered_packages


def test_env_example_documents_required_variables() -> None:
    env_example = (PROJECT_ROOT / ".env.example").read_text().splitlines()
    documented_variables = {
        line.split("=", 1)[0] for line in env_example if "=" in line and not line.startswith("#")
    }

    required = {
        "GEMINI_API_KEY",
        "NEO4J_PASSWORD",
        "NEO4J_URI",
        "NEO4J_USER",
        "QDRANT_COLLECTION",
        "QDRANT_HOST",
        "QDRANT_PORT",
        "EMBEDDING_DIMENSIONS",
        "EMBEDDING_MODEL",
        "EMBEDDING_PROVIDER",
        "OPENROUTER_API_KEY",
        "LOCAL_EMBEDDING_DIMENSIONS",
        "LOCAL_EMBEDDING_MODEL",
        "GEMINI_EMBEDDING_TASK",
        "LLM_PROVIDER",
        "SPARSE_SEARCH_ENABLED",
        "SPARSE_EMBEDDING_MODEL",
    }

    assert required.issubset(documented_variables), (
        f"Missing from .env.example: {required - documented_variables}"
    )
