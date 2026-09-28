"""Tests for the plain in-memory TTL cache: a hit within TTL skips
fetch_fn entirely, an expired/missing entry re-fetches, and a raising
fetch_fn never poisons the cache with a failure."""
import time

import pytest

from ai.market_intelligence.providers import cache


def test_first_call_invokes_fetch_fn_and_caches_result():
    calls = []

    def fetch():
        calls.append(1)
        return "value"

    result = cache.get_or_fetch("key1", 60, fetch)
    assert result == "value"
    assert len(calls) == 1


def test_second_call_within_ttl_skips_fetch_fn():
    calls = []

    def fetch():
        calls.append(1)
        return "value"

    cache.get_or_fetch("key2", 60, fetch)
    cache.get_or_fetch("key2", 60, fetch)
    assert len(calls) == 1


def test_call_after_ttl_expiry_refetches(monkeypatch):
    calls = []

    def fetch():
        calls.append(1)
        return f"value{len(calls)}"

    cache.get_or_fetch("key3", 0.01, fetch)
    time.sleep(0.02)
    result = cache.get_or_fetch("key3", 0.01, fetch)

    assert len(calls) == 2
    assert result == "value2"


def test_different_keys_are_cached_independently():
    cache.get_or_fetch("key_a", 60, lambda: "a")
    cache.get_or_fetch("key_b", 60, lambda: "b")
    assert cache.get_or_fetch("key_a", 60, lambda: "unused") == "a"
    assert cache.get_or_fetch("key_b", 60, lambda: "unused") == "b"


def test_raising_fetch_fn_does_not_cache_a_failure():
    calls = []

    def fetch():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return "recovered"

    with pytest.raises(RuntimeError):
        cache.get_or_fetch("key4", 60, fetch)

    result = cache.get_or_fetch("key4", 60, fetch)
    assert result == "recovered"
    assert len(calls) == 2


def test_clear_removes_all_entries():
    calls = []
    cache.get_or_fetch("key5", 60, lambda: calls.append(1) or "v")
    cache.clear()
    cache.get_or_fetch("key5", 60, lambda: calls.append(1) or "v")
    assert len(calls) == 2
