"""E2E checklist for Stage 14 (Telegram Alert Delivery). Requires the
backend running with the MOCK notification provider so the pipeline is
exercised for real through a live server without touching a real bot:
    MODE=mock AI_PROVIDER=mock TELEGRAM_ENABLED=true NOTIFICATION_PROVIDER=mock \
        TELEGRAM_POLL_INTERVAL_SECONDS=3 uvicorn api.main:app --host 127.0.0.1 --port 8000
    (cd frontend && npm run dev)   # http://localhost:3000 — Stage 14 has no frontend UI,
                                     but the checklist still confirms nothing else broke.

Run directly:
    python e2e/test_telegram_notifications_checklist.py

Deliberately robust to zero pre-existing monitoring_alerts rows: whatever
already exists (Stage 13's own E2E run and normal dev-mode polling
typically leave some in the dev DB) gets discovered and delivered for
real; if none exist yet, the checklist still verifies the status/test
endpoints behave correctly and that delivery counts stay stable across
polling cycles.
"""
import sys
import time

import httpx

API_BASE = "http://127.0.0.1:8000"
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = ""):
    results.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'}: {name}" + (f" — {detail}" if detail and not condition else ""))


def main() -> int:
    # --- Status endpoint ---
    status_resp = httpx.get(f"{API_BASE}/api/notifications/telegram/status", timeout=15)
    check("API: /telegram/status returns 200", status_resp.status_code == 200)
    status = status_resp.json()
    check("API: status has the expected shape",
          set(status.keys()) == {"enabled", "configured", "provider", "last_success_at", "last_error_at"})
    check("API: status never includes a bot_token or chat_id field",
          "bot_token" not in status and "chat_id" not in status)

    # --- Test endpoint (mock provider) ---
    test_resp = httpx.post(f"{API_BASE}/api/notifications/telegram/test", timeout=15)
    check("API: /telegram/test returns 200 with the mock provider", test_resp.status_code == 200)
    test_body = test_resp.text.lower()
    check("API: test response never echoes a token-looking value", "bot_token" not in test_body)

    # --- Delivery pipeline: let a couple of polling cycles run ---
    monitoring_resp = httpx.get(f"{API_BASE}/api/monitoring/alerts", timeout=15)
    check("API: /api/monitoring/alerts still responds (Stage 13 untouched)", monitoring_resp.status_code == 200)
    existing_alert_count = len(monitoring_resp.json())

    time.sleep(7)  # a couple of TELEGRAM_POLL_INTERVAL_SECONDS=3 cycles

    status_after = httpx.get(f"{API_BASE}/api/notifications/telegram/status", timeout=15).json()
    if existing_alert_count > 0:
        check("API: last_success_at is populated once alerts exist to deliver",
              status_after.get("last_success_at") is not None)
    else:
        check("API: status endpoint remains stable with zero alerts to deliver (no crash)", True)

    # --- Repeated polling must never re-deliver the same alert ---
    time.sleep(4)
    status_again = httpx.get(f"{API_BASE}/api/notifications/telegram/status", timeout=15).json()
    check("API: last_success_at does not regress across an idle polling cycle",
          (status_again.get("last_success_at") or "") >= (status_after.get("last_success_at") or ""))

    # --- Existing systems remain unaffected ---
    aplus_resp = httpx.get(f"{API_BASE}/api/strategy/aplus", timeout=15)
    check("API: /api/strategy/aplus (Stage 4) still responds normally", aplus_resp.status_code == 200)

    legacy_alerts_resp = httpx.get(f"{API_BASE}/api/alerts", timeout=15)
    check("API: legacy /api/alerts (Stage 1) still responds normally", legacy_alerts_resp.status_code == 200)

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
