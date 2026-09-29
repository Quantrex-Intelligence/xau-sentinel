"""E2E checklist for Stage 17 (Strategy Analytics).
Requires both servers running in MOCK mode with AI_PROVIDER=mock:
    MODE=mock AI_PROVIDER=mock uvicorn api.main:app --host 127.0.0.1 --port 8000
    (cd frontend && npm run dev)   # http://localhost:3000

Run directly:
    python e2e/test_strategy_analytics_checklist.py

Seeds a couple of closed trades via the real /api/journal/trades endpoints,
pinned to a far-future trade_date and selected by table row position, not a
formatted price string — see [[feedback-e2e-test-data-hygiene]] (same
lesson applied proactively in test_trade_review_checklist.py).
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


def wait_for(page: Page, text: str, timeout: int = 15000) -> bool:
    try:
        page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def _seed_closed_trade(direction: str, result: str, planned_rr: float) -> int:
    created = httpx.post(f"{API_BASE}/api/journal/trades", timeout=15, json={
        "trade_date": "2099-12-30", "trade_time": "12:00", "direction": direction,
        "entry": 3700.0, "stop_loss": 3690.0, "take_profit": 3730.0, "planned_rr": planned_rr,
    }).json()
    trade_id = created["id"]
    r_multiple = planned_rr if result == "WIN" else (-1.0 if result == "LOSS" else 0.0)
    httpx.patch(f"{API_BASE}/api/journal/trades/{trade_id}/close", timeout=15, json={
        "exit_price": 3730.0, "result": result, "pnl": 100.0 * r_multiple, "r_multiple": r_multiple,
        "duration_minutes": 30,
    })
    return trade_id


def main() -> int:
    ids = [
        _seed_closed_trade("BUY", "WIN", 3.0),
        _seed_closed_trade("BUY", "LOSS", 3.0),
        _seed_closed_trade("SELL", "WIN", 2.0),
    ]
    check("API: seeded closed trades for this checklist", all(i > 0 for i in ids))

    # --- Overview endpoint ---
    resp = httpx.get(f"{API_BASE}/api/strategy-analytics", timeout=15)
    check("API: GET /strategy-analytics returns 200", resp.status_code == 200)
    body = resp.json()
    check("API: overview total_trades counts at least the seeded trades", body["overview"]["total_trades"] >= 3)
    check("API: strategy_alignment_counts present and sums to total_trades",
          sum(body["overview"]["strategy_alignment_counts"].values()) == body["overview"]["total_trades"])
    check("API: adherence is a list", isinstance(body["adherence"], list))
    all_text = str(body).lower()
    check("API: overview never mentions best/worst/winning-setup/probability language",
          not any(w in all_text for w in ("best setup", "worst setup", "winning setup", "probability")))

    # --- Dimension breakdown endpoint ---
    dim_resp = httpx.get(f"{API_BASE}/api/strategy-analytics/dimensions/direction", timeout=15)
    check("API: GET /strategy-analytics/dimensions/direction returns 200", dim_resp.status_code == 200)
    dim_body = dim_resp.json()
    check("API: direction breakdown includes a BUY row", any(r["value"] == "BUY" for r in dim_body["rows"]))

    bad_dim_resp = httpx.get(f"{API_BASE}/api/strategy-analytics/dimensions/not_a_real_dimension", timeout=15)
    check("API: unknown dimension name returns 400", bad_dim_resp.status_code == 400)

    # --- Immutability: hitting analytics endpoints must never change the trades ---
    trade_after = httpx.get(f"{API_BASE}/api/journal/trades/{ids[0]}", timeout=15).json()
    check("API: seeded trade unchanged after hitting analytics endpoints", trade_after.get("result") == "WIN")

    # --- Browser checks ---
    console_errors, page_errors, failed_requests = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}"))

        page.goto(f"{BASE}/analytics", wait_until="networkidle", timeout=30000)
        check("UI: Analytics page loads", wait_for(page, "Total Trades"))
        check("UI: Strategy Analytics panel renders", wait_for(page, "Strategy Analytics"))
        check("UI: Median R stat renders", wait_for(page, "Median R"))
        check("UI: Strategy Alignment counts render", wait_for(page, "Strategy Alignment"))
        check("UI: Adherence vs. Outcome table renders", wait_for(page, "Adherence vs. Outcome"))
        check("UI: Dimension Breakdown panel renders", wait_for(page, "Dimension Breakdown"))
        check("UI: default Direction breakdown shows a BUY row", wait_for(page, "BUY"))

        regime_button = page.get_by_text("Regime", exact=True)
        if regime_button.count() > 0:
            regime_button.click()
            check("UI: switching dimension re-renders the table", wait_for(page, "Sample", timeout=8000))
        else:
            check("UI: Regime dimension button present", False, "button not found")

        check("UI: no best/worst/winning-setup language anywhere on the page",
              not any(w in page.inner_text("body").lower() for w in ("best setup", "worst setup", "winning setup")))
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
