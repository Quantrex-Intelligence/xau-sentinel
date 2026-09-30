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


# ---------------------------------------------------------------------------
# OP-004 follow-up: production logging actually reaches real output. The
# original OP-004 fix (logger.info() calls in ai/monitoring/engine.py)
# passed its own unit test but never appeared in real `docker compose logs`
# output, because nothing in the app's real startup path had ever
# configured a handler for logger.info() to reach anywhere -- caplog's own
# handler attaches directly to the logger under test and bypasses that gap
# entirely, which is exactly why it didn't catch this. These tests check
# the actual global logging configuration api/main.py now applies at import
# time, not a caplog-isolated view of it.
# ---------------------------------------------------------------------------

def test_httpx_and_httpcore_stay_pinned_to_warning_despite_the_new_root_config():
    """VAL-036/log_safety.py's own documented risk: raising the root level
    to INFO is exactly what would start leaking the Telegram bot token via
    httpx's per-request URL log line, unless log_safety.install() (which
    runs immediately after the new basicConfig() call in api/main.py) keeps
    overriding these two loggers specifically."""
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_monitoring_logs_reach_real_stdout_in_a_fresh_process():
    """The genuine, container-level version of this check. A same-process
    test (asserting on logging.getLogger().handlers, or capturing via
    capfd/caplog) is NOT trustworthy here and was tried first: pytest's own
    logging plugin attaches a handler to the root logger before any test
    module is ever imported, which makes api/main.py's
    `logging.basicConfig(...)` call -- correctly documented as a no-op when
    the root logger already has a handler -- silently do nothing *inside
    pytest specifically*, regardless of whether the fix genuinely works in
    a real process. Confirmed directly: `python -c "import logging;
    print(logging.getLogger().handlers)"` outside pytest shows `[]`
    (nothing configured yet, so basicConfig() will take effect), while the
    same check from inside a pytest test shows a pre-existing handler.

    A subprocess is a fresh Python process with no pytest anywhere in it --
    the same starting state uvicorn itself has in the real container, and
    the only way to actually prove `docker compose logs api` would show
    this line."""
    import subprocess
    import sys as _sys
    from pathlib import Path

    marker = "OP-004-REAL-STDOUT-CHECK-3f1a9c"
    result = subprocess.run(
        [_sys.executable, "-c",
         f"import api.main; import logging; logging.getLogger('ai.monitoring.engine').info({marker!r})"],
        capture_output=True, text=True, timeout=30,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert result.returncode == 0, f"subprocess failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    assert marker in result.stdout, f"stdout={result.stdout!r} stderr={result.stderr!r}"
