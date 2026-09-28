"""E2E checklist for Stage 8 (Historical Setup Similarity). Requires both
servers running in MOCK mode with AI_PROVIDER=mock (see
e2e/test_migration_checklist.py for how to start them). Run directly:
    python e2e/test_historical_similarity_checklist.py
"""
import sys

import httpx
from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
API_BASE = "http://127.0.0.1:8000"
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = ""):
    results.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'}: {name}" + (f" — {detail}" if detail and not condition else ""))


def _create_trade(direction="BUY"):
    return httpx.post(f"{API_BASE}/api/journal/trades", timeout=10, json={
        "trade_date": "2026-01-05", "trade_time": "09:00:00", "direction": direction,
        "entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0, "planned_rr": 2.0, "setup": "Sweep+MSS",
    }).json()


def main() -> int:
    # --- API-level checks ---
    tools = httpx.get(f"{API_BASE}/api/ai/tools", timeout=10).json()
    check("API: find_similar_setups tool is registered",
          any(t["name"] == "find_similar_setups" for t in tools))

    current = httpx.get(f"{API_BASE}/api/similarity/current", timeout=10).json()
    check("API: /similarity/current returns query_features and matches",
          "query_features" in current and "matches" in current)

    trade_a = _create_trade()
    trade_b = _create_trade()
    trade_similarity = httpx.get(
        f"{API_BASE}/api/similarity/trade/{trade_a['id']}", timeout=10, params={"min_similarity": 0.0}
    ).json()
    trade_ids = {m["trade_id"] for m in trade_similarity["matches"]}
    check("API: a trade never matches itself", trade_a["id"] not in trade_ids)
    check("API: a trade finds another similar historical trade", trade_b["id"] in trade_ids)

    check("API: response never mentions probability/confidence",
          "probability" not in httpx.get(f"{API_BASE}/api/similarity/current", timeout=10).text.lower()
          and "confidence" not in httpx.get(f"{API_BASE}/api/similarity/current", timeout=10).text.lower())

    unknown_trade = httpx.get(f"{API_BASE}/api/similarity/trade/999999", timeout=10)
    check("API: unknown trade id returns 404", unknown_trade.status_code == 404)

    chat_resp = httpx.post(f"{API_BASE}/api/ai/chat", timeout=15,
                            json={"message": "have I seen a setup like this before?"}).json()
    check("API: chat response still has the pre-existing fields",
          all(k in chat_resp for k in ("answer", "context_used", "sources", "knowledge_used",
                                        "tools_used", "memory_used")))

    # --- Browser checks ---
    console_errors, page_errors, failed_requests = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}"))

        page.goto(f"{BASE}/setups", wait_until="networkidle", timeout=30000)
        try:
            page.get_by_text("Historical Similarity", exact=False).wait_for(state="visible", timeout=15000)
            check("UI: Historical Similarity panel renders on the Setups page", True)
        except Exception:
            check("UI: Historical Similarity panel renders on the Setups page", False)

        try:
            page.get_by_text("A+ Strategy Evaluation", exact=False).wait_for(state="visible", timeout=10000)
            check("UI: Stage 4 A+ panel still renders (not disturbed by Stage 8)", True)
        except Exception:
            check("UI: Stage 4 A+ panel still renders (not disturbed by Stage 8)", False)

        page.wait_for_timeout(2000)
        body_text = page.inner_text("body")
        check("UI: no probability/confidence-of-success language anywhere on the page",
              "probability" not in body_text.lower() and "chance of winning" not in body_text.lower())

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
