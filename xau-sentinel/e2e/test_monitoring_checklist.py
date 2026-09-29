"""E2E checklist for Stage 13 (Real-Time Monitoring & In-App Alert Engine).
Requires both servers running in MOCK mode:
    MODE=mock AI_PROVIDER=mock uvicorn api.main:app --host 127.0.0.1 --port 8000
    (cd frontend && npm run dev)   # http://localhost:3000

Run directly (not via pytest):
    python e2e/test_monitoring_checklist.py

Deliberately robust to zero alerts existing yet: mock market data is
wall-clock-bar-aligned (a new M5 bar only every 5 real minutes — see
ai/monitoring/'s own docstrings), so a short E2E run cannot reliably force
a real state transition. Alert-*generation* correctness is proven by
tests/test_monitoring_rules.py and tests/test_monitoring_engine.py
(directly-constructed snapshots, no wall-clock dependency); this checklist
proves the UI/API plumbing works end to end with whatever alerts — real or
none — happen to exist by the time it runs, the same tolerance
test_strategy_aplus_checklist.py already has for its own rating.
"""
import sys

import httpx
from playwright.sync_api import Page, sync_playwright

BASE = "http://localhost:3000"
API_BASE = "http://127.0.0.1:8000"
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = ""):
    results.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'}: {name}" + (f" — {detail}" if detail and not condition else ""))


def wait_for(page: Page, text: str, timeout: int = 20000) -> bool:
    try:
        page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def main() -> int:
    # --- API-level checks ---
    resp = httpx.get(f"{API_BASE}/api/monitoring/alerts", timeout=15)
    check("API: /api/monitoring/alerts returns 200", resp.status_code == 200)
    alerts = resp.json()
    check("API: alerts response is a list", isinstance(alerts, list))

    unread_resp = httpx.get(f"{API_BASE}/api/monitoring/alerts/unread", timeout=15)
    check("API: /api/monitoring/alerts/unread returns 200", unread_resp.status_code == 200)

    body_text = resp.text.lower()
    check("API: response never mentions probability/win-forecast language",
          "probability" not in body_text and "win_chance" not in body_text and "will win" not in body_text)

    ack_all_resp = httpx.post(f"{API_BASE}/api/monitoring/alerts/acknowledge-all", timeout=15)
    check("API: /acknowledge-all returns 200 with a count field",
          ack_all_resp.status_code == 200 and "count" in ack_all_resp.json())

    legacy_resp = httpx.get(f"{API_BASE}/api/alerts", timeout=15)
    check("API: legacy /api/alerts is untouched and still responds",
          legacy_resp.status_code == 200 and isinstance(legacy_resp.json(), list))

    # --- Browser checks ---
    console_errors, page_errors, failed_requests = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}"))

        page.goto(f"{BASE}/", wait_until="networkidle", timeout=30000)

        bell = page.get_by_label("Notifications")
        try:
            bell.wait_for(state="visible", timeout=15000)
            check("UI: notification bell renders in the top bar", True)
        except Exception:
            check("UI: notification bell renders in the top bar", False)

        bell.click()
        page.wait_for_timeout(500)
        dropdown_opened = wait_for(page, "Notifications", timeout=5000) or wait_for(page, "No unread alerts", timeout=1000)
        check("UI: clicking the bell opens the notification dropdown", dropdown_opened)

        has_empty_state = wait_for(page, "No unread alerts.", timeout=2000)
        has_alert_row = wait_for(page, "Acknowledge", timeout=2000)
        check("UI: dropdown shows either the empty state or at least one alert row",
              has_empty_state or has_alert_row)

        show_all = page.get_by_text("Show all", exact=False)
        try:
            show_all.click(timeout=5000)
            page.wait_for_timeout(1000)
            check("UI: 'Show all' history toggle works without erroring", True)
        except Exception:
            check("UI: 'Show all' history toggle works without erroring", False)

        # Repeated polling must never duplicate a visible unread entry —
        # wait through one more poll cycle and confirm the dropdown is
        # still internally consistent (no crash, no duplicate DOM error).
        page.wait_for_timeout(2000)
        check("UI: dropdown remains stable across a polling cycle (no crash)",
              wait_for(page, "Notifications", timeout=5000))

        page.goto(f"{BASE}/setups", wait_until="networkidle", timeout=30000)
        check("UI: bell also renders on the Setups page (global, not page-local)",
              wait_for(page, "Notifications", timeout=1000) or page.get_by_label("Notifications").is_visible())

        check("UI: no browser console errors", len(console_errors) == 0 and len(page_errors) == 0,
              str(console_errors + page_errors))
        check("UI: no failed network requests", len(failed_requests) == 0, str(failed_requests))

        browser.close()

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
