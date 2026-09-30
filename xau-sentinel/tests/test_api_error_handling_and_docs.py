"""DEP-015: an unhandled exception becomes a logged JSON 500 that still
carries CORS headers. DEP-006: API docs can be switched off via
config.API_DOCS_ENABLED. TestClient is used without a `with` block so the
app lifespan (DB init, background loops) never runs."""
import logging

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import config
from api import main as api_main

ORIGIN = api_main.DEFAULT_ORIGINS[0]


@pytest.fixture
def app_with_failing_routes(monkeypatch):
    monkeypatch.delenv("XAU_API_CORS_ORIGINS", raising=False)
    app = api_main.create_app()

    @app.get("/__test__/boom")
    def boom():
        raise RuntimeError("kaboom")

    @app.get("/__test__/not-found")
    def not_found():
        raise HTTPException(status_code=404, detail="nope")

    return app


def test_unhandled_exception_returns_json_500_with_cors_header(app_with_failing_routes, caplog):
    client = TestClient(app_with_failing_routes, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="api.main"):
        response = client.get("/__test__/boom", headers={"Origin": ORIGIN})

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert response.headers.get("access-control-allow-origin") == ORIGIN
    assert "kaboom" not in response.text  # no internals leaked to the client
    records = [r for r in caplog.records if r.name == "api.main"]
    assert records and records[0].exc_info is not None
    assert "/__test__/boom" in records[0].getMessage()


def test_http_exception_is_not_swallowed(app_with_failing_routes):
    client = TestClient(app_with_failing_routes, raise_server_exceptions=False)
    response = client.get("/__test__/not-found", headers={"Origin": ORIGIN})
    assert response.status_code == 404
    assert response.json() == {"detail": "nope"}
    assert response.headers.get("access-control-allow-origin") == ORIGIN


def test_normal_routes_still_work(app_with_failing_routes):
    client = TestClient(app_with_failing_routes)
    response = client.get("/api/health", headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_docs_enabled(monkeypatch):
    monkeypatch.setattr(config, "API_DOCS_ENABLED", True)
    client = TestClient(api_main.create_app())
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 200, path


def test_api_docs_disabled(monkeypatch):
    monkeypatch.setattr(config, "API_DOCS_ENABLED", False)
    client = TestClient(api_main.create_app())
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path
    assert client.get("/api/health").status_code == 200


def test_api_docs_env_var_parsing(monkeypatch):
    monkeypatch.setenv("API_DOCS_ENABLED", "false")
    assert config._env_bool("API_DOCS_ENABLED", True) is False
    monkeypatch.delenv("API_DOCS_ENABLED")
    assert config._env_bool("API_DOCS_ENABLED", True) is True
