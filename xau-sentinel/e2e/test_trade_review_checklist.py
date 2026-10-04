"""E2E checklist for Stage 16 (Trade Review & Behavioral Intelligence).
Requires both servers running in MOCK mode with AI_PROVIDER=mock:
    MODE=mock AI_PROVIDER=mock uvicorn api.main:app --host 127.0.0.1 --port 8000
    (cd frontend && npm run dev)   # http://localhost:3000

Run directly:
    python e2e/test_trade_review_checklist.py

Seeds its own closed trade via the real /api/journal/trades endpoints
(the same pattern test_migration_checklist.py's own UI flow exercises,
done here via API for speed/determinism) — deterministic review never
depends on live market timing, unlike Stage 13's monitoring alerts.
"""
import sys
from pathlib import Path

import httpx
from playwright.sync_api import Page, sync_playwright

# `python e2e/<file>.py` puts e2e/ on sys.path, not the project root, so add the
# xau-sentinel root explicitly before importing the production safety detector.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai.prompts import contains_predictive_probability_claim  # noqa: E402

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


def _seed_closed_trade() -> int:
    # journal.trades.list_trades() orders by trade_date DESC, trade_time DESC — a
    # far-future date pins this seeded trade to the top row regardless of what
    # else already exists in the persistent dev DB, so the UI can select it by
    # row position rather than by a formatted price string (a fixed literal
    # string breaks Playwright's strict-mode get_by_text across repeated runs).
    created = httpx.post(f"{API_BASE}/api/journal/trades", timeout=15, json={
        "trade_date": "2099-12-31", "trade_time": "23:59", "direction": "BUY",
        "entry": 3700.0, "stop_loss": 3690.0, "take_profit": 3730.0, "planned_rr": 3.0,
    }).json()
    trade_id = created["id"]
    httpx.patch(f"{API_BASE}/api/journal/trades/{trade_id}/close", timeout=15, json={
        "exit_price": 3730.0, "result": "WIN", "pnl": 300.0, "r_multiple": 3.0, "duration_minutes": 45,
    })
    return trade_id


def main() -> int:
    trade_id = _seed_closed_trade()
    check("API: seeded a closed trade for this checklist", trade_id > 0)

    # --- Deterministic review — must never call the LLM ---
    resp = httpx.get(f"{API_BASE}/api/trade-review/{trade_id}", timeout=15)
    check("API: GET /trade-review/{id} returns 200", resp.status_code == 200)
    body = resp.json()
    check("API: outcome is one of the known values", body.get("outcome") in ("WIN", "LOSS", "BREAKEVEN", "OPEN", "UNKNOWN"))
    check("API: strategy_alignment is one of the known values",
          body.get("strategy_alignment") in ("ALIGNED", "PARTIALLY_ALIGNED", "NOT_ALIGNED", "UNKNOWN"))
    check("API: interpretation is null before any generate call", body.get("interpretation") is None)

    unknown_resp = httpx.get(f"{API_BASE}/api/trade-review/999999999", timeout=15)
    check("API: unknown trade id returns 404", unknown_resp.status_code == 404)

    # --- AI review — an explicit, separate action ---
    generated = httpx.post(f"{API_BASE}/api/trade-review/{trade_id}/generate", timeout=20).json()
    check("API: POST /generate populates an interpretation", bool(generated.get("interpretation")))
    # Semantic check, not a bare-word search: the production safety net that decides
    # whether a predictive claim slipped through. Negated disclaimers such as "does not
    # imply probability for the outcome" are allowed; real forecasts and paraphrases are not.
    interpretation = generated.get("interpretation") or ""
    generated_text = interpretation.lower()
    check("API: generated review contains no predictive probability/win-forecast claim",
          not contains_predictive_probability_claim(interpretation))
    check("API: generated review contains no trading instruction",
          "buy now" not in generated_text and "sell now" not in generated_text)

    # --- Immutability: generating a review must never change the trade itself ---
    trade_after = httpx.get(f"{API_BASE}/api/journal/trades/{trade_id}", timeout=15).json()
    check("API: trade result/outcome unchanged after generating a review", trade_after.get("result") == "WIN")

    # --- Summary / patterns ---
    summary_resp = httpx.get(f"{API_BASE}/api/trade-review/summary", timeout=15)
    check("API: /trade-review/summary returns 200", summary_resp.status_code == 200)
    summary = summary_resp.json()
    check("API: summary trades_reviewed counts at least the seeded trade", summary.get("trades_reviewed", 0) >= 1)

    patterns_resp = httpx.get(f"{API_BASE}/api/trade-review/patterns", timeout=15)
    check("API: /trade-review/patterns returns a list", patterns_resp.status_code == 200
          and isinstance(patterns_resp.json(), list))

    # --- Browser checks ---
    console_errors, page_errors, failed_requests = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}"))

        page.goto(f"{BASE}/journal", wait_until="networkidle", timeout=30000)
        check("UI: Journal page loads", wait_for(page, "NEW TRADE"))
        check("UI: Trade Review Overview panel renders", wait_for(page, "Trade Review Overview"))
        check("UI: overview shows a trades-reviewed count", wait_for(page, "Trades reviewed"))

        # Open the seeded trade's detail sheet — it sorts to the top row
        # (see _seed_closed_trade) so we select by position, not by a
        # formatted price string.
        page.locator("table tbody tr").first.click()
        opened = wait_for(page, "Review Trade", timeout=10000)
        check("UI: closed trade detail shows a Review Trade action", opened)

        if opened:
            page.get_by_text("Review Trade", exact=True).click()
            check("UI: deterministic review renders instantly (Strategy alignment)",
                  wait_for(page, "Strategy alignment", timeout=8000))
            check("UI: rule observations render", wait_for(page, "Rule Observations", timeout=3000))

            generate_button = page.get_by_text("Generate AI review", exact=True)
            if generate_button.count() > 0:
                generate_button.click()
                check("UI: AI Review section renders after generation",
                      wait_for(page, "AI Review", timeout=15000))
            else:
                check("UI: AI review already present (cached from the API call above)",
                      wait_for(page, "AI Review", timeout=3000))

        check("UI: no predictive probability/win-forecast claim anywhere on the page",
              not contains_predictive_probability_claim(page.inner_text("body")))
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
