from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import decisionssearch.interfaces.http.asgi as asgi_module
from decisionssearch.interfaces.http.http_app import create_http_app
from decisionssearch.interfaces.mcp.main import create_app


def test_create_http_app_exposes_health_route_and_shares_container() -> None:
    container = object()

    app = create_http_app(container)

    assert app.state.container is container

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_asgi_app_mounts_api_and_mcp_with_shared_container() -> None:
    container = object()
    http_app = create_http_app(container)
    mcp_app = FastAPI()

    @mcp_app.get("/")
    async def root() -> dict[str, str]:
        return {"status": "mcp-ok"}

    app = asgi_module.create_asgi_app(container=container, http_app=http_app, mcp_app=mcp_app)

    assert app.state.container is container
    assert app.state.http_app is http_app
    assert http_app.state.container is container

    with TestClient(app) as client:
        api_response = client.get("/api/health")
        mcp_response = client.get("/mcp/")

    assert api_response.status_code == 200
    assert api_response.json() == {"status": "ok"}
    assert mcp_response.status_code == 200
    assert mcp_response.json() == {"status": "mcp-ok"}


def test_create_app_keeps_default_streamable_http_path_for_standalone_usage() -> None:
    app = create_app(container=object())

    assert getattr(app, "settings").streamable_http_path == "/mcp"


def test_create_asgi_app_initializes_real_mcp_mount() -> None:
    app = asgi_module.create_asgi_app(container=object())

    with TestClient(app, raise_server_exceptions=False, base_url="http://localhost:8000") as client:
        response = client.get("/mcp/")

    assert response.status_code == 406
    assert "Not Acceptable" in response.text
    assert "mcp-session-id" in response.headers


def test_create_asgi_app_passes_same_container_to_mcp_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    container = object()
    observed: dict[str, object] = {}

    class FakeMCP:
        def streamable_http_app(self) -> FastAPI:
            app = FastAPI()

            @app.get("/")
            async def root() -> dict[str, str]:
                return {"status": "mcp-ok"}

            return app

    def fake_create_mcp_app(*, container: object, streamable_http_path: str):
        observed["container"] = container
        observed["streamable_http_path"] = streamable_http_path
        return FakeMCP()

    monkeypatch.setattr(asgi_module, "create_mcp_app", fake_create_mcp_app)

    app = asgi_module.create_asgi_app(container=container)

    assert observed == {
        "container": container,
        "streamable_http_path": "/",
    }

    with TestClient(app) as client:
        response = client.get("/mcp/")

    assert response.status_code == 200
    assert response.json() == {"status": "mcp-ok"}


def test_create_app_propagates_registration_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import decisionssearch.interfaces.mcp.prompts as prompts_module
    import decisionssearch.interfaces.mcp.resources as resources_module
    import decisionssearch.interfaces.mcp.tools as tools_module

    monkeypatch.setattr(prompts_module, "register_prompts", lambda app: None)
    monkeypatch.setattr(resources_module, "register_resources", lambda app, container: None)

    def fail_register_tools(app, container) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(tools_module, "register_tools", fail_register_tools)

    with pytest.raises(RuntimeError, match="boom"):
        create_app(container=object())


def test_module_level_app_is_lazy_until_first_use() -> None:
    import decisionssearch.interfaces.mcp.main as main_module

    assert hasattr(main_module.app, "_app")
    assert main_module.app._app is None


def test_importing_server_main_does_not_import_container_module() -> None:
    import importlib
    import sys

    sys.modules.pop("decisionssearch.interfaces.mcp.main", None)
    sys.modules.pop("decisionssearch.bootstrap.container", None)

    importlib.import_module("decisionssearch.interfaces.mcp.main")

    assert "decisionssearch.bootstrap.container" not in sys.modules
