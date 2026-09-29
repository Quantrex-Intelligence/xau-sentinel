"""API-level tests for /api/monitoring/alerts — thin pass-throughs over
ai.monitoring.store, mounted at a distinct prefix from the pre-existing,
unrelated /api/alerts (see api/routes/monitoring.py's own docstring for
why). TestClient(app) triggers the real FastAPI lifespan, but
MONITORING_ENABLED=False (pinned by conftest.py's autouse fixture) keeps
the background polling loop from starting during tests."""
import inspect

import pytest
from fastapi.testclient import TestClient

from ai.monitoring import store
from ai.monitoring.models import AlertEvent, AlertType, Severity
from api.main import app


@pytest.fixture
def api_client(temp_db):
    store.init_table()
    with TestClient(app) as client:
        yield client


def _seed(dedup_key="k1", **overrides):
    defaults = dict(
        type=AlertType.SETUP_STATE_CHANGED, severity=Severity.INFO, title="Setup changed",
        message="NO SETUP -> DEVELOPING", dedup_key=dedup_key, payload={"foo": "bar"},
    )
    defaults.update(overrides)
    return store.create_alert(AlertEvent(**defaults))


def test_get_alerts_returns_seeded_alerts(api_client):
    _seed()
    resp = api_client.get("/api/monitoring/alerts")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["type"] == "SETUP_STATE_CHANGED"
    assert body[0]["acknowledged"] is False


def test_get_alerts_filters_by_type(api_client):
    _seed(dedup_key="k1", type=AlertType.SETUP_STATE_CHANGED)
    _seed(dedup_key="k2", type=AlertType.RISK_STATUS_CHANGED)
    resp = api_client.get("/api/monitoring/alerts", params={"type": "RISK_STATUS_CHANGED"})
    body = resp.json()
    assert len(body) == 1
    assert body[0]["type"] == "RISK_STATUS_CHANGED"


def test_get_alerts_filters_by_severity(api_client):
    _seed(dedup_key="k1", severity=Severity.INFO)
    _seed(dedup_key="k2", severity=Severity.CRITICAL)
    resp = api_client.get("/api/monitoring/alerts", params={"severity": "CRITICAL"})
    body = resp.json()
    assert len(body) == 1
    assert body[0]["severity"] == "CRITICAL"


def test_get_alerts_respects_limit(api_client):
    for i in range(5):
        _seed(dedup_key=f"k{i}")
    resp = api_client.get("/api/monitoring/alerts", params={"limit": 2})
    assert len(resp.json()) == 2


def test_get_unread_alerts_excludes_acknowledged(api_client):
    a = _seed(dedup_key="k1")
    _seed(dedup_key="k2")
    store.acknowledge(a.id)

    resp = api_client.get("/api/monitoring/alerts/unread")
    body = resp.json()
    assert len(body) == 1
    assert body[0]["acknowledged"] is False


def test_acknowledge_alert_marks_it_read(api_client):
    a = _seed(dedup_key="k1")
    resp = api_client.post(f"/api/monitoring/alerts/{a.id}/acknowledge")
    assert resp.status_code == 200
    assert resp.json()["acknowledged"] is True

    unread = api_client.get("/api/monitoring/alerts/unread").json()
    assert unread == []


def test_acknowledge_unknown_alert_returns_404(api_client):
    resp = api_client.post("/api/monitoring/alerts/99999/acknowledge")
    assert resp.status_code == 404


def test_acknowledge_all_clears_unread(api_client):
    _seed(dedup_key="k1")
    _seed(dedup_key="k2")
    resp = api_client.post("/api/monitoring/alerts/acknowledge-all")
    assert resp.status_code == 200
    assert resp.json()["count"] == 2

    unread = api_client.get("/api/monitoring/alerts/unread").json()
    assert unread == []


def test_acknowledge_all_on_empty_table_returns_zero(api_client):
    resp = api_client.post("/api/monitoring/alerts/acknowledge-all")
    assert resp.json()["count"] == 0


def test_monitoring_alerts_path_is_distinct_from_the_legacy_alerts_route(api_client):
    """Stage 1's /api/alerts (api/routes/alerts.py) and Stage 13's
    /api/monitoring/alerts must never collide — this proves both resolve
    independently and the legacy route is untouched."""
    _seed(dedup_key="k1")
    monitoring_resp = api_client.get("/api/monitoring/alerts")
    legacy_resp = api_client.get("/api/alerts")
    assert monitoring_resp.status_code == 200
    assert legacy_resp.status_code == 200
    # The legacy route's shape has no `acknowledged`/`type`/`dedup_key` fields.
    if legacy_resp.json():
        assert "acknowledged" not in legacy_resp.json()[0]


def test_monitoring_routes_never_touch_trades_or_strategy_or_fundednext_tables():
    """Structural guarantee: acknowledge only ever sets
    monitoring_alerts.acknowledged — there is no code path here that could
    modify trades, strategy state, market data, risk calculations, or A+
    ratings."""
    import api.routes.monitoring as monitoring_route
    source = inspect.getsource(monitoring_route)
    for banned in ("trades_repo", "journal.trades", "fundednext_journal", "strategy.evaluator", "risk.fundednext"):
        assert banned not in source
