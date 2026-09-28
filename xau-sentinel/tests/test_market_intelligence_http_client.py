"""Tests for the thin httpx-based get_json()/get_text() helpers: correct
URL/params/timeout/User-Agent wiring, and that HTTP errors propagate
unwrapped (real.py is the layer that catches them, not this module)."""
import httpx
import pytest

import config
from ai.market_intelligence.providers import http_client


class _FakeResponse:
    def __init__(self, json_data=None, text_data="", status_code=200):
        self._json_data = json_data
        self.text = text_data
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


def test_get_json_returns_parsed_body_and_sets_user_agent(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _FakeResponse(json_data={"ok": True})

    monkeypatch.setattr(httpx, "get", fake_get)
    result = http_client.get_json("https://example.com/data", params={"a": 1})

    assert result == {"ok": True}
    assert captured["url"] == "https://example.com/data"
    assert captured["params"] == {"a": 1}
    assert "User-Agent" in captured["headers"]
    assert captured["timeout"] == config.MARKET_INTEL_HTTP_TIMEOUT_SECONDS


def test_get_json_uses_explicit_timeout_override(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["timeout"] = timeout
        return _FakeResponse(json_data={})

    monkeypatch.setattr(httpx, "get", fake_get)
    http_client.get_json("https://example.com/data", timeout=2.5)
    assert captured["timeout"] == 2.5


def test_get_text_returns_raw_body(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(text_data="<rss></rss>"))
    assert http_client.get_text("https://example.com/feed.xml") == "<rss></rss>"


def test_get_json_raises_on_http_error_status(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(status_code=500))
    with pytest.raises(httpx.HTTPStatusError):
        http_client.get_json("https://example.com/data")


def test_get_json_propagates_connection_errors(monkeypatch):
    def fake_get(*a, **k):
        raise httpx.ConnectError("boom", request=None)

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(httpx.ConnectError):
        http_client.get_json("https://example.com/data")
